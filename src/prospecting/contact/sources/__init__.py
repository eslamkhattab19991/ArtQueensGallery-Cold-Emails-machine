"""Contact-discovery source plugins, each implementing ``ContactSource``.

A source performs one discovery method and knows nothing about the other sources,
the scheduler, ownership classification, or ranking. It reports failure as a
returned outcome, never as a raised exception, so that one failing source cannot
abort the parallel group it runs in.
"""
