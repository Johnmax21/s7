import os

# Guard heavy ML imports so module import never raises
HAS_ML_LIBS = True
try:
    import pandas as pd
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, roc_auc_score
    import joblib
except Exception:
    HAS_ML_LIBS = False
    pd = None
    np = None
    RandomForestClassifier = None
    train_test_split = None
    accuracy_score = None
    roc_auc_score = None
    joblib = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, 'game_history.csv')
MODEL_FILE = os.path.join(BASE_DIR, 'card_model.joblib')

__all__ = ["build_dataset", "train_and_save", "load_model", "predict_best_card"]

def _ensure_ml_available():
    if not HAS_ML_LIBS:
        raise RuntimeError("ML libraries not available: install pandas, numpy, scikit-learn, joblib")

def build_dataset():
    """
    Read HISTORY_FILE and build a pandas DataFrame of pairwise features.
    Requires ML libs and access to PlayerCard model.
    """
    _ensure_ml_available()
    if not os.path.exists(HISTORY_FILE):
        raise FileNotFoundError(HISTORY_FILE)

    # import Django model here to avoid circular import at module load
    from .models import PlayerCard

    df = pd.read_csv(HISTORY_FILE)
    required = {'player_card_id', 'computer_card_id', 'outcome', 'batting_team'}
    if not required.issubset(set(df.columns)):
        raise ValueError(f"History CSV missing required columns: {required - set(df.columns)}")

    cards_qs = PlayerCard.objects.all()
    cards = {c.id: {'batting': c.batting, 'bowling': c.bowling, 'runs': c.runs} for c in cards_qs}

    rows = []
    for _, r in df.iterrows():
        try:
            pid = int(r['player_card_id']); cid = int(r['computer_card_id'])
        except Exception:
            continue
        p = cards.get(pid); c = cards.get(cid)
        if p is None or c is None:
            continue

        batting_team = str(r.get('batting_team'))
        outcome = str(r.get('outcome')).lower()
        if outcome == 'win':
            comp_success = 1 if batting_team == 'computer' else 0
        else:
            comp_success = 1 if batting_team == 'player' else 0

        rows.append({
            'p_batting': p['batting'], 'p_bowling': p['bowling'], 'p_runs': p['runs'],
            'c_batting': c['batting'], 'c_bowling': c['bowling'], 'c_runs': c['runs'],
            'innings': int(r.get('innings', 1)) if 'innings' in r else 1,
            'round_number': int(r.get('round_number', 0)) if 'round_number' in r else 0,
            'wickets': int(r.get('wickets', 0)) if 'wickets' in r else 0,
            'label': comp_success
        })

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        raise ValueError("No training data after processing history.")
    return dataset

def train_and_save(test_size=0.2, random_state=42):
    _ensure_ml_available()
    df = build_dataset()
    X = df.drop(columns=['label'])
    y = df['label']
    strat = y if len(y.unique()) > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=random_state, stratify=strat)
    model = RandomForestClassifier(n_estimators=200, random_state=random_state, n_jobs=-1)
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)[:,1] if hasattr(model, "predict_proba") else None
    print("Accuracy:", accuracy_score(y_test, preds))
    if probs is not None:
        try:
            print("AUC:", roc_auc_score(y_test, probs))
        except Exception:
            pass
    joblib.dump(model, MODEL_FILE)
    print("Saved model to", MODEL_FILE)
    return MODEL_FILE

def load_model():
    """Return loaded model or None (safe to call even if ML libs not present)."""
    if not HAS_ML_LIBS:
        return None
    if os.path.exists(MODEL_FILE):
        return joblib.load(MODEL_FILE)
    return None

def predict_best_card(player_card_id, candidate_card_ids, innings=1, round_number=0, wickets=0):
    """
    Return (best_card_id, probability) or (None, None) if no model available.
    Imports PlayerCard inside function to avoid circular imports.
    """
    if not HAS_ML_LIBS:
        return None, None
    model = load_model()
    if model is None:
        return None, None

    from .models import PlayerCard

    player = PlayerCard.objects.get(id=player_card_id)
    candidates = PlayerCard.objects.filter(id__in=candidate_card_ids)
    rows = []
    ids = []
    for c in candidates:
        rows.append({
            'p_batting': player.batting,
            'p_bowling': player.bowling,
            'p_runs': player.runs,
            'c_batting': c.batting,
            'c_bowling': c.bowling,
            'c_runs': c.runs,
            'innings': innings,
            'round_number': round_number,
            'wickets': wickets
        })
        ids.append(c.id)
    X = pd.DataFrame(rows)
    probs = model.predict_proba(X)[:,1] if hasattr(model, "predict_proba") else model.predict(X)
    best_idx = int(np.argmax(probs))
    return ids[best_idx], float(probs[best_idx])

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        train_and_save()
    else:
        print("Usage: python ai_model.py train")