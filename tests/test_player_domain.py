from __future__ import annotations

import unittest

from xiuxian3.domain.player import Player, PlayerStatus


class PlayerDomainTests(unittest.TestCase):
    def test_new_player_has_safe_initial_state(self) -> None:
        player = Player.new(
            player_id="player-1",
            external_id="qq-1",
            nickname="qq-1",
        )
        self.assertEqual(player.status, PlayerStatus.ACTIVE)
        self.assertEqual(player.realm, "凡人")
        self.assertEqual(player.level, 1)
        self.assertEqual(player.cultivation, 0)
        self.assertEqual(player.spirit_stones, 0)
        self.assertEqual(player.stamina, 100)

    def test_player_rejects_empty_identity_and_negative_assets(self) -> None:
        with self.assertRaises(ValueError):
            Player.new(player_id="", external_id="qq-1", nickname="qq-1")
        with self.assertRaises(ValueError):
            Player(
                player_id="player-1",
                external_id="qq-1",
                nickname="qq-1",
                realm="凡人",
                level=1,
                cultivation=-1,
                spirit_stones=0,
                stamina=100,
                status=PlayerStatus.ACTIVE,
            )
