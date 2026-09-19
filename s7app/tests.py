import time
from unittest import TestCase
from s7app import game_engine

class MockCard:
    def __init__(self, name, batting, bowling, runs, ability=None, is_spinner=False, id=1):
        self.id = id
        self.name = name
        self.batting = batting
        self.bowling = bowling
        self.runs = runs
        self.ability = ability
        self.is_spinner = is_spinner
        self.image = None

class TestGameEngine(TestCase):

    def test_apply_abilities_no_bonus(self):
        batter = MockCard('Batter', 80, 50, 10)
        bowler = MockCard('Bowler', 50, 80, 5)
        state = {'scores': {}}
        eff_batting, eff_bowling, eff_runs, runs_cutter, log = game_engine.apply_abilities(
            batter, bowler, round_number=3, state=state, batting_team='player1'
        )
        self.assertEqual(eff_batting, 80)
        self.assertEqual(eff_bowling, 80)
        self.assertEqual(eff_runs, 10)
        self.assertFalse(runs_cutter)
        self.assertEqual(len(log), 0)

    def test_apply_abilities_opener_and_powerplay(self):
        batter = MockCard('Batter', 80, 50, 10, ability='opener')
        bowler = MockCard('Bowler', 50, 80, 5, ability='powerplay_specialist')
        state = {'scores': {}}
        
        # Round 1 - abilities should trigger (+10 each)
        eff_batting, eff_bowling, eff_runs, runs_cutter, log = game_engine.apply_abilities(
            batter, bowler, round_number=1, state=state, batting_team='player1'
        )
        self.assertEqual(eff_batting, 90)
        self.assertEqual(eff_bowling, 90)
        
        # Round 3 - abilities should not trigger
        eff_batting, eff_bowling, eff_runs, runs_cutter, log = game_engine.apply_abilities(
            batter, bowler, round_number=3, state=state, batting_team='player1'
        )
        self.assertEqual(eff_batting, 80)
        self.assertEqual(eff_bowling, 80)

    def test_apply_abilities_spin_basher(self):
        batter = MockCard('Batter', 80, 50, 10, ability='spin_basher')
        bowler = MockCard('Bowler', 50, 80, 5, is_spinner=True)
        state = {'scores': {}}
        
        eff_batting, eff_bowling, _, _, log = game_engine.apply_abilities(
            batter, bowler, round_number=4, state=state, batting_team='player1'
        )
        self.assertEqual(eff_batting, 90)

    def test_apply_abilities_runs_cutter(self):
        batter = MockCard('Batter', 80, 50, 20)
        bowler = MockCard('Bowler', 50, 80, 5, ability='runs_cutter')
        state = {'scores': {}}
        
        _, _, eff_runs, runs_cutter, _ = game_engine.apply_abilities(
            batter, bowler, round_number=4, state=state, batting_team='player1'
        )
        self.assertTrue(runs_cutter)
        self.assertEqual(eff_runs, 20)  # applies in resolve_round, not here

    def test_resolve_round_win(self):
        batter = MockCard('Batter', 90, 50, 10)
        bowler = MockCard('Bowler', 50, 80, 5)
        state = {'scores': {'player1': 0, 'player2': 0}, 'wickets': {'player1': 0, 'player2': 0}}
        
        state = game_engine.resolve_round(state, 1, 1, 'player1', 'player1', batter, bowler)
        self.assertEqual(state['scores']['player1'], 10)
        self.assertEqual(state['wickets']['player1'], 0)
        self.assertEqual(state['runs_in_round_1_1'], 10)
        self.assertEqual(state['wicket_in_round_1_1'], False)

    def test_resolve_round_tie(self):
        batter = MockCard('Batter', 80, 50, 10)
        bowler = MockCard('Bowler', 50, 80, 5)
        state = {'scores': {'player1': 0, 'player2': 0}, 'wickets': {'player1': 0, 'player2': 0}}
        
        state = game_engine.resolve_round(state, 1, 1, 'player1', 'player1', batter, bowler)
        self.assertEqual(state['scores']['player1'], 3)
        self.assertEqual(state['wickets']['player1'], 0)

    def test_resolve_round_wicket(self):
        batter = MockCard('Batter', 70, 50, 10)
        bowler = MockCard('Bowler', 50, 80, 5)
        state = {'scores': {'player1': 0, 'player2': 0}, 'wickets': {'player1': 0, 'player2': 0}}
        
        state = game_engine.resolve_round(state, 1, 1, 'player1', 'player1', batter, bowler)
        self.assertEqual(state['scores']['player1'], 0)
        self.assertEqual(state['wickets']['player1'], 1)

    def test_recalculate_round_with_boost(self):
        batter = MockCard('Batter', 80, 50, 10, id=101)
        bowler = MockCard('Bowler', 50, 80, 5, id=202)
        state = {'scores': {'player1': 0, 'player2': 0}, 'wickets': {'player1': 0, 'player2': 0}}
        
        # Initial resolution (Tie -> 3 runs)
        state = game_engine.resolve_round(state, 1, 1, 'player1', 'player1', batter, bowler)
        self.assertEqual(state['scores']['player1'], 3)
        self.assertEqual(state['wicket_in_round_1_1'], False)
        
        # Apply boost for batter (+10) -> (90 vs 80) Win -> 10 runs
        state = game_engine.recalculate_round_with_boost(state, 1, 1, 'player1', 10)
        
        self.assertEqual(state['scores']['player1'], 10)
        self.assertEqual(state['wicket_in_round_1_1'], False)
        self.assertEqual(state['runs_in_round_1_1'], 10)

    def test_end_conditions_innings_transition(self):
        state = {
            'scores': {'player1': 50, 'player2': 0},
            'wickets': {'player1': 10, 'player2': 0},
            'round_number': 3
        }
        state = game_engine._check_end_conditions(state, 1, 2, 'player1', 'player1')
        self.assertIn('innings_transition', state)
        self.assertEqual(state['innings_transition']['target'], 51)
        
    def test_end_conditions_game_over(self):
        state = {
            'scores': {'player1': 50, 'player2': 51},
            'wickets': {'player1': 10, 'player2': 4},
            'target': 51,
            'round_number': 3
        }
        state = game_engine._check_end_conditions(state, 2, 2, 'player2', 'player1')
        self.assertTrue(state.get('game_over_pending'))
        self.assertEqual(state['winner'], 'player2')
