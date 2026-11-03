# P-005 mutation results

The 128 mutations comprise 122 caught (112 test failures and 10 timeouts),
5 unviable and 1 untestable on Windows. There are no remaining missed mutants.
The ten timeouts persisted with a 180-second test timeout and count as caught
under the migration rules. The original and continuation results are retained
in the migration bridge.

The timed-out `Reader::take` return replacements and `Reader::binding` return
replacements bypass the normal advancement of `reader.rest`. The two `parse`
mutations invert loop or recovery conditions. These mutations can make the
parser repeat without consuming input; the observed timeout does not establish
which fixture hangs in each case. They remain identified as timeouts.

The missed `read` mutation changes `supported || metadata.file_type().is_fifo()`
to `&&`. It is compiled only on Unix and is untestable on Windows. It is not
an equivalent: verify it with a real FIFO test on Unix.
