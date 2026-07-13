from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
import time
import json
from django.utils import timezone

from game.models import (
    ActiveGame,
    GameResult,
    PuzzleStats,
    Achievement,
    UserAchievement,
)
from game.services import (
    create_or_update_active_game,
    delete_active_game,
    unlock_achievement,
    check_game_achievements,
    check_puzzle_achievements,
    update_opening_progress,
    cleanup_stale_games,
)

User = get_user_model()

INITIAL_BOARD = [
    ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'],
    ['p', 'p', 'p', 'p', 'p', 'p', 'p', 'p'],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None, None],
    ['P', 'P', 'P', 'P', 'P', 'P', 'P', 'P'],
    ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
]


class TestAchievementServices(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="password"
        )
        # Seed achievements
        achievement_codes = [
            "FIRST_WIN", "WIN_10", "WIN_50", "WIN_100",
            "PLAY_10", "PLAY_20", "PLAY_50", "PLAY_100", "PLAY_500",
            "FIRST_CHECKMATE", "FIFTH_CHECKMATE", "CHECKMATE_10",
            "CHECKMATE_20", "CHECKMATE_30", "CHECKMATE_50", "CHECKMATE_100",
            "STALEMATE_DRAW", "FAST_WIN",
            "FIRST_PUZZLE", "PUZZLE_10", "PUZZLE_25", "PUZZLE_50",
            "PUZZLE_75", "PUZZLE_100", "PUZZLE_200",
            "STREAK_3", "STREAK_7", "STREAK_10", "STREAK_30", "STREAK_50",
            "STREAK_100"
        ]
        for code in achievement_codes:
            Achievement.objects.create(
                code=code, title=code, description=code, rarity="common"
            )

    def test_unlock_achievement(self):
        # Verify no-op when user is None
        unlock_achievement(None, "FIRST_WIN")
        self.assertEqual(UserAchievement.objects.count(), 0)

        # Ignore unknown achievement codes
        unlock_achievement(self.user, "UNKNOWN_CODE")
        self.assertEqual(UserAchievement.objects.count(), 0)

        # Ensure a UserAchievement is created for a valid code
        unlock_achievement(self.user, "FIRST_WIN")
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="FIRST_WIN"
            ).exists()
        )

        # Calling the function multiple times should not create duplicates
        unlock_achievement(self.user, "FIRST_WIN")
        self.assertEqual(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="FIRST_WIN"
            ).count(),
            1
        )

    def test_check_game_achievements(self):
        # Ensure no-op when user is None
        check_game_achievements(None)
        self.assertEqual(UserAchievement.objects.count(), 0)

        # Create games: 9 wins (play total 9)
        for _ in range(9):
            GameResult.objects.create(
                user=self.user,
                mode="pvp",
                winner="white",
                end_reason="resign",
                player_color="white"
            )

        check_game_achievements(self.user)
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="FIRST_WIN"
            ).exists()
        )
        self.assertFalse(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="WIN_10"
            ).exists()
        )
        self.assertFalse(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="PLAY_10"
            ).exists()
        )

        # Add 1 more win to reach 10
        GameResult.objects.create(
            user=self.user,
            mode="pvp",
            winner="white",
            end_reason="resign",
            player_color="white"
        )
        check_game_achievements(self.user)
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="WIN_10"
            ).exists()
        )
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="PLAY_10"
            ).exists()
        )

        # Checkmates
        GameResult.objects.create(
            user=self.user,
            mode="pvp",
            winner="white",
            end_reason="checkmate",
            player_color="white"
        )
        check_game_achievements(self.user)
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="FIRST_CHECKMATE"
            ).exists()
        )

        # FAST_WIN should unlock only when the game is won in < 20 moves
        GameResult.objects.create(
            user=self.user,
            mode="pvp",
            winner="white",
            end_reason="resign",
            player_color="white",
            moves=["e4"] * 19
        )
        check_game_achievements(self.user)
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="FAST_WIN"
            ).exists()
        )

        # Validate that >= 20 moves does not unlock FAST_WIN
        UserAchievement.objects.all().delete()
        GameResult.objects.all().delete()
        GameResult.objects.create(
            user=self.user,
            mode="pvp",
            winner="white",
            end_reason="resign",
            player_color="white",
            moves=["e4"] * 20
        )
        check_game_achievements(self.user)
        self.assertFalse(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="FAST_WIN"
            ).exists()
        )

    def test_check_puzzle_achievements(self):
        stats = PuzzleStats.objects.create(
            user=self.user,
            puzzles_solved=9,
            current_streak=2,
            best_streak=2
        )

        # Verify no-op when user is None
        check_puzzle_achievements(None, stats)
        self.assertEqual(UserAchievement.objects.count(), 0)

        # Test boundaries
        check_puzzle_achievements(self.user, stats)
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="FIRST_PUZZLE"
            ).exists()
        )
        self.assertFalse(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="PUZZLE_10"
            ).exists()
        )
        self.assertFalse(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="STREAK_3"
            ).exists()
        )

        stats.puzzles_solved = 10
        stats.current_streak = 3
        stats.best_streak = 3
        stats.save()
        check_puzzle_achievements(self.user, stats)
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="PUZZLE_10"
            ).exists()
        )
        self.assertTrue(
            UserAchievement.objects.filter(
                user=self.user, achievement__code="STREAK_3"
            ).exists()
        )


class TestOpeningServices(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="password"
        )

    def test_update_opening_progress(self):
        # Verify accuracy_percentage calculation
        progress, first = update_opening_progress(
            self.user, "Italian Game", correct_move=True
        )
        self.assertEqual(progress.correct_moves, 1)
        self.assertEqual(progress.accuracy_percentage, 100.0)
        self.assertFalse(first)

        progress, first = update_opening_progress(
            self.user, "Italian Game", incorrect_move=True
        )
        self.assertEqual(progress.correct_moves, 1)
        self.assertEqual(progress.incorrect_moves, 1)
        self.assertEqual(progress.accuracy_percentage, 50.0)

        # Ensure completion_percentage is capped at 100%
        progress, first = update_opening_progress(
            self.user, "Italian Game", checkpoint=120
        )
        self.assertEqual(progress.completion_percentage, 100.0)

        # openings_completed should increment only the first time
        progress, first = update_opening_progress(
            self.user, "Italian Game", completed=True
        )
        self.assertTrue(first)
        self.assertEqual(progress.openings_completed, 1)

        progress, first = update_opening_progress(
            self.user, "Italian Game", completed=True
        )
        self.assertFalse(first)
        self.assertEqual(progress.openings_completed, 1)

        # Newly created progress should initialize openings_started = 1
        progress2, _ = update_opening_progress(self.user, "Ruy Lopez")
        self.assertEqual(progress2.openings_started, 1)

        # Verify no-op when user is None
        self.assertIsNone(update_opening_progress(None, "Sicilian Defense"))


class TestActiveGameServices(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser", password="password"
        )

    def test_create_or_update_active_game(self):
        request = self.factory.get("/")
        middleware = SessionMiddleware(lambda _: None)
        middleware.process_request(request)
        request.session.save()

        request.user = self.user

        # Create a record for an active game
        create_or_update_active_game(request, {"game_status": "active"})
        self.assertTrue(
            ActiveGame.objects.filter(
                session_key=request.session.session_key
            ).exists()
        )

        active_game = ActiveGame.objects.get(
            session_key=request.session.session_key
        )
        self.assertEqual(active_game.user, self.user)
        self.assertEqual(active_game.status, "active")
        self.assertEqual(active_game.game_state, {"game_status": "active"})

        # Delete the record when game_status is not "active"
        create_or_update_active_game(request, {"game_status": "checkmate"})
        self.assertFalse(
            ActiveGame.objects.filter(
                session_key=request.session.session_key
            ).exists()
        )

        # Support anonymous session-based games
        request.user = type(
            "AnonymousUser", (object,), {"is_authenticated": False}
        )()
        create_or_update_active_game(request, {"game_status": "active"})
        anon_game = ActiveGame.objects.get(
            session_key=request.session.session_key
        )
        self.assertIsNone(anon_game.user)
        self.assertIsNone(anon_game.game_state)

    def test_delete_active_game(self):
        request = self.factory.get("/")
        middleware = SessionMiddleware(lambda _: None)
        middleware.process_request(request)
        request.session.save()

        ActiveGame.objects.create(
            session_key=request.session.session_key, status="active"
        )

        # Delete the active game when a session exists
        delete_active_game(request)
        self.assertFalse(
            ActiveGame.objects.filter(
                session_key=request.session.session_key
            ).exists()
        )

        # No-op when no session key exists (not saved yet)
        request2 = self.factory.get("/")
        middleware.process_request(request2)
        delete_active_game(request2)  # Should not raise exception


class ActiveGamePersistenceTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testplayer", password="password"
        )
        self.client.force_login(self.user)
        self.game_state = {
            'board': INITIAL_BOARD,
            'current_turn': 'white',
            'move_history': [],
            'captured': {'white': [], 'black': []},
            'white_time': 600,
            'black_time': 600,
            'time_limit': 600,
            'increment': 0,
            'last_ts': time.time(),
            'paused': False,
            'mode': 'pvp',
            'player_color': 'white',
            'game_status': 'active'
        }

    def test_cross_device_resume(self):
        # 1. Start a game on device 1
        response = self.client.post('/api/new-game/', json.dumps({
            'mode': 'pvp',
            'time_limit': 600
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        # Check active game in database
        ag = ActiveGame.objects.filter(user=self.user, status="active").first()
        self.assertIsNotNone(ag)
        
        # 2. Open a new session / device (by logging out and logging in again)
        self.client.logout()
        self.client.force_login(self.user)
        
        # Call resume-game
        response_resume = self.client.post('/api/resume/', content_type='application/json')
        self.assertEqual(response_resume.status_code, 200)
        self.assertTrue(response_resume.json()['valid'])
        
        # Verify the session key on the active game is updated to the new session key
        ag.refresh_from_db()
        new_session_key = self.client.session.session_key
        self.assertEqual(ag.session_key, new_session_key)

    def test_session_refresh_rotation(self):
        # Start a game
        self.client.post('/api/new-game/', json.dumps({
            'mode': 'pvp',
            'time_limit': 600
        }), content_type='application/json')
        
        ag = ActiveGame.objects.filter(user=self.user, status="active").first()
        old_session_key = ag.session_key
        
        # Simulate session key rotation by creating a new session store
        from django.contrib.sessions.backends.db import SessionStore
        from django.conf import settings
        session = self.client.session
        session_data = dict(session.items())
        
        new_session = SessionStore()
        for k, v in session_data.items():
            new_session[k] = v
        new_session.save()
        
        new_session_key = new_session.session_key
        self.client.cookies[settings.SESSION_COOKIE_NAME] = new_session_key
        
        # Call resume-game or make a move to trigger key update
        response = self.client.post('/api/resume/', content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        ag.refresh_from_db()
        self.assertEqual(ag.session_key, new_session_key)
        self.assertNotEqual(ag.session_key, old_session_key)

    def test_optimistic_locking_conflict(self):
        # Start a game
        response = self.client.post('/api/new-game/', json.dumps({
            'mode': 'pvp',
            'time_limit': 600
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        init_version = response.json()['version']
        
        # Play a move (A) with version = init_version
        move_payload = {
            'from_row': 6, 'from_col': 4,
            'to_row': 4, 'to_col': 4,
            'version': init_version
        }
        response_a = self.client.post('/api/move/', json.dumps(move_payload), content_type='application/json')
        self.assertEqual(response_a.status_code, 200)
        self.assertTrue(response_a.json()['valid'])
        new_version = response_a.json()['version']
        self.assertEqual(new_version, init_version + 1)
        
        # Play another move (B) but send the stale init_version (optimistic lock conflict)
        move_payload_stale = {
            'from_row': 1, 'from_col': 4,
            'to_row': 3, 'to_col': 4,
            'version': init_version
        }
        response_b = self.client.post('/api/move/', json.dumps(move_payload_stale), content_type='application/json')
        self.assertEqual(response_b.status_code, 409)
        self.assertIn('Conflict', response_b.json()['error'])

    def test_game_completion(self):
        # Start a game
        self.client.post('/api/new-game/', json.dumps({
            'mode': 'pvp',
            'time_limit': 600
        }), content_type='application/json')
        
        ag = ActiveGame.objects.filter(user=self.user, status="active").first()
        self.assertIsNotNone(ag)
        
        # Resign the game (completed)
        response = self.client.post('/api/resign/', json.dumps({
            'resigning_player': 'white'
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        # Verify that ActiveGame is deleted
        self.assertFalse(ActiveGame.objects.filter(user=self.user).exists())
        
        # Verify that GameResult is created
        self.assertEqual(GameResult.objects.filter(user=self.user).count(), 1)

    def test_stale_cleanup(self):
        # Create a stale game for authenticated user
        ag = ActiveGame.objects.create(
            user=self.user,
            session_key="auth_stale_session_123",
            game_state={
                'board': INITIAL_BOARD,
                'current_turn': 'white',
                'move_history': [1, 2, 3, 4, 5, 6],  # >= 5 moves -> resignation
                'player_color': 'white',
                'mode': 'pvp',
                'game_status': 'active'
            },
            status="active",
            version=1
        )
        # Update last_activity_at to be stale (50 hours ago)
        ActiveGame.objects.filter(pk=ag.pk).update(
            last_activity_at=timezone.now() - timezone.timedelta(hours=50)
        )
        
        deleted, resigned = cleanup_stale_games()
        self.assertEqual(deleted, 0)
        self.assertEqual(resigned, 1)
        self.assertFalse(ActiveGame.objects.filter(pk=ag.pk).exists())
        self.assertEqual(GameResult.objects.filter(user=self.user).count(), 1)

    def test_anonymous_gameplay_fallback(self):
        self.client.logout()  # Make request anonymous
        
        # Start game
        response = self.client.post('/api/new-game/', json.dumps({
            'mode': 'pvp',
            'time_limit': 600
        }), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['version'], 0)
        
        # Verify ActiveGame tracking record exists but game_state is None
        ag = ActiveGame.objects.filter(session_key=self.client.session.session_key).first()
        self.assertIsNotNone(ag)
        self.assertIsNone(ag.game_state)
        
        # Make a move
        move_payload = {
            'from_row': 6, 'from_col': 4,
            'to_row': 4, 'to_col': 4
        }
        response_move = self.client.post('/api/move/', json.dumps(move_payload), content_type='application/json')
        self.assertEqual(response_move.status_code, 200)
        self.assertEqual(response_move.json()['version'], 0)
        
        # Game state in db must remain None (preserving session-only flow)
        ag.refresh_from_db()
        self.assertIsNone(ag.game_state)
