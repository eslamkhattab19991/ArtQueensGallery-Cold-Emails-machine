"""One module per pipeline stage.

Each stage has exactly one input shape and one output shape, reads and writes
JSONL, and never mutates its input file. A stage must not import another stage;
shared behaviour belongs in a lower layer.

Stage order (see ARCHITECTURE.md §4)::

    s1_input -> s2_discovery -> s3_extraction -> s4_qualification
             -> s5_contact_discovery -> s6_verification
             -> s6b_personalization -> s7_export
"""
