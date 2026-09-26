"""Expected negative content decisions, distinct from broken services or code."""


class CandidateRejected(ValueError):
    """A checked candidate cannot be used; choosing another one is expected."""


class DraftRejected(CandidateRejected):
    """Generated content failed bounded local validation; never ready to render."""
