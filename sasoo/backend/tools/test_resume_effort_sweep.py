"""Safety checks for the append-only effort sweep recovery budget."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from tools import luna_compare as c
from tools.resume_effort_sweep import ConservativeJournal


def test_unsettled_reservation_counts_against_budget(tmp_path):
    journal = ConservativeJournal(c.Options(campaign=tmp_path / "campaign"), tmp_path / "global")
    states = {
        "complete": c.JournalEntry(run_id="complete", state="settled", amount_usd="0.02", at="t"),
        "unknown": c.JournalEntry(run_id="unknown", state="unsettled", amount_usd="0.03", at="t"),
    }
    with patch.object(journal, "states", return_value=states), \
            patch.object(c, "historical_cost", return_value=Decimal("0.70")):
        assert journal.spent() == Decimal("0.75")


def test_interrupted_reservation_blocks_recovery(tmp_path):
    journal = ConservativeJournal(c.Options(campaign=tmp_path / "campaign"), tmp_path / "global")
    states = {"pending": c.JournalEntry(run_id="pending", state="reserved",
                                         amount_usd="0.03", at="t")}
    with patch.object(journal, "states", return_value=states), \
            patch.object(c, "historical_cost", return_value=Decimal("0.70")):
        with pytest.raises(c.ComparisonError, match="interrupted reservation"):
            journal.spent()
