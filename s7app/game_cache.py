from django.core.cache import cache
import logging
import time

logger = logging.getLogger(__name__)

# 3 hours TTL for game state
GAME_TTL = 60 * 60 * 3

def redis_key(room_code):
    return f'game:{room_code}:state'

def get_game_state(room_code):
    """
    Get game state from Redis.
    If not in Redis, load from DB and cache it.
    """
    key = redis_key(room_code)
    
    _start = time.time()
    try:
        state = cache.get(key)
        _elapsed = time.time() - _start
        if _elapsed > 0.05:  # log anything over 50ms
            print(f"⏱️ REDIS GET took {_elapsed*1000:.1f}ms for {room_code}")
        
        if state is not None:
            state.setdefault('scores', {'player1': 0, 'player2': 0})
            state.setdefault('wickets', {'player1': 0, 'player2': 0})
            return state
    except Exception as e:
        logger.warning(f'Redis get failed: {e}')
        print(f"❌ REDIS GET FAILED for {room_code}: {e}")
    
    # Redis miss — load from DB
    _db_start = time.time()
    from .models import GameRoom
    try:
        room = GameRoom.objects.get(code=room_code)
        _db_elapsed = time.time() - _db_start
        print(f"⏱️ DB FALLBACK GET took {_db_elapsed*1000:.1f}ms for {room_code}")
        
        state = room.state or {}
        state.setdefault('scores', {'player1': 0, 'player2': 0})
        state.setdefault('wickets', {'player1': 0, 'player2': 0})
        # Warm up Redis
        try:
            cache.set(key, state, GAME_TTL)
        except Exception as e:
            logger.warning(f'Redis set failed: {e}')
        return state
    except GameRoom.DoesNotExist:
        return {
            'scores':  {'player1': 0, 'player2': 0},
            'wickets': {'player1': 0, 'player2': 0},
        }


def save_game_state(room_code, state, save_to_db=False):
    """
    Always save to Redis (fast).
    Save to DB only at important moments.
    """
    key = redis_key(room_code)
    
    # Save to Redis
    _start = time.time()
    try:
        cache.set(key, state, GAME_TTL)
        _elapsed = time.time() - _start
        if _elapsed > 0.05:
            print(f"⏱️ REDIS SET took {_elapsed*1000:.1f}ms for {room_code}")
    except Exception as e:
        logger.warning(f'Redis save failed: {e}')
        print(f"❌ REDIS SET FAILED for {room_code}: {e}")
        # If Redis fails, force DB save
        save_to_db = True
    
    # Save to DB if requested
    if save_to_db:
        _db_start = time.time()
        from .models import GameRoom
        try:
            room = GameRoom.objects.get(code=room_code)
            room.state = state
            room.save(update_fields=['state'])
            _db_elapsed = time.time() - _db_start
            print(f"⏱️ DB SAVE took {_db_elapsed*1000:.1f}ms for {room_code}")
        except GameRoom.DoesNotExist:
            pass


def delete_game_state(room_code):
    """Clear Redis after match fully ends"""
    key = redis_key(room_code)
    try:
        cache.delete(key)
    except Exception as e:
        logger.warning(f'Redis delete failed: {e}')


# When to save to DB:
# 1. Game over
# 2. Innings transition
# 3. Both players played a round (resolve round)
# NOT needed:
# 1. One player picked a card (waiting for opponent)
# 2. Support/boost activation