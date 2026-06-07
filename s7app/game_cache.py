from django.core.cache import cache
import logging

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
    
    try:
        state = cache.get(key)
        if state is not None:
            return state
    except Exception as e:
        logger.warning(f'Redis get failed: {e}')
    
    # Redis miss — load from DB
    from .models import GameRoom
    try:
        room = GameRoom.objects.get(code=room_code)
        state = room.state or {}
        # Warm up Redis
        try:
            cache.set(key, state, GAME_TTL)
        except Exception as e:
            logger.warning(f'Redis set failed: {e}')
        return state
    except GameRoom.DoesNotExist:
        return {}


def save_game_state(room_code, state, save_to_db=False):
    """
    Always save to Redis (fast).
    Save to DB only at important moments.
    """
    key = redis_key(room_code)
    
    # Save to Redis
    try:
        cache.set(key, state, GAME_TTL)
    except Exception as e:
        logger.warning(f'Redis save failed: {e}')
        # If Redis fails, force DB save
        save_to_db = True
    
    # Save to DB if requested
    if save_to_db:
        from .models import GameRoom
        try:
            room = GameRoom.objects.get(code=room_code)
            room.state = state
            room.save(update_fields=['state'])
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