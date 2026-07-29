# The clean pass is audio-only, reads raw takes, and does not own final loudness

The pipeline reads the raw per-speaker WAVs, emits cleaned mono WAVs at a working
level, and stops. Censoring, syncing, mixing and the final distribution loudness all
happen in the NLE, which is where the takes are summed. The previous script stamped a
distribution-final −16 LUFS onto each take separately, which is incorrect the moment
two such tracks are mixed — the sum overshoots. Carrying video was also dropped: the
takes are synced by hand in the NLE anyway, so remuxing bought nothing and cost a
gigabyte of I/O per run.

## Consequences

Nothing in this repo produces a distribution master; if that ever needs automating it
is a separate concern operating on the NLE's mixdown, not an extra mode here. Takes
must be re-synced in the NLE because the clean tracks are bare audio, and the two
takes are already 65 ms different in length.
