# Where this audit disagrees with the review

Empty is not the expected end state. The research phase found that eight of
eight design-critical claims came back "partly right" when challenged, and a
peer review is no more exempt from that than the code is.

## H12, second half: the analog sample rate, partly

**The review is right that older "10 MSPS" claims needed re-checking, and
wrong if read as saying they were false.**

The decoder work established that a capture below about 13 MSPS can appear to
lock while producing a wrong image. That is true of a signal at the
modulation depth this toolkit's own synthesiser uses, whose peak white sits at
+6.4 MHz of deviation.

It is not established for real transmitters, and the one real measurement in
the record points the other way: a whoop VTX decoded at 10 MSPS with under
0.3 % of its energy outside +/-4.5 MHz *(verified: verdict 5)*. The RTC6705
datasheet gives no video deviation figure, so how far a given VTX swings is
unknown until someone measures it.

The first pass of this audit rewrote three documents as though the synthetic
figure governed real hardware, which would have replaced a measurement with a
model. That is the H8 error running backwards, and it is recorded here because
the audit committed it before catching it.

**Resolution:** both claims kept, each with its scope stated. 20 MSPS is the
recommendation under either reading.

**Open question for the maintainer:** none. Measuring the actual deviation of
the FPV rig, once there is time, would settle it, and Q18 already asks what
the rig is.
