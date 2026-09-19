from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether)

styles = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=15, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor('#1a3c5a'))
H2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=12, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor('#1a3c5a'))
B = ParagraphStyle('B', parent=styles['Normal'], fontSize=9.2, leading=12.5)
S = ParagraphStyle('S', parent=B, fontSize=8, leading=10.5)
C = ParagraphStyle('C', parent=B, fontName='Courier', fontSize=7.8, leading=10, leftIndent=8, backColor=colors.HexColor('#f3f5f7'))
T = ParagraphStyle('T', parent=styles['Title'], fontSize=18, spaceAfter=4)
SUB = ParagraphStyle('SUB', parent=B, textColor=colors.HexColor('#555555'))

def P(t, st=B): return Paragraph(t, st)
def bullets(items, st=B):
    return [Paragraph('&bull; ' + i, ParagraphStyle('bl', parent=st, leftIndent=10, firstLineIndent=-8)) for i in items]

def tbl(rows, widths, header=True, st=S):
    data = [[Paragraph(c, st) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    ts = [('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#9aa5b1')),
          ('VALIGN', (0,0), (-1,-1), 'TOP'),
          ('LEFTPADDING', (0,0), (-1,-1), 4), ('RIGHTPADDING', (0,0), (-1,-1), 4),
          ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]
    if header:
        ts += [('BACKGROUND', (0,0), (-1,0), colors.HexColor('#dfe7ef'))]
    t.setStyle(TableStyle(ts))
    return t

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(colors.HexColor('#666666'))
    canvas.drawString(20*mm, 10*mm, doc.title)
    canvas.drawRightString(190*mm, 10*mm, 'page %d' % doc.page)
    canvas.restoreState()

# ------------------------------------------------------------------ Document A
def doc_a(path):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title='Tsukorok S3v4 fw 5.5.12 - detection methods, alarm logic, ranking, TDOA suitability',
                            author='AERIX RF research')
    s = []
    s.append(P('Tsukorok S3 v4 firmware 5.5.12', T))
    s.append(P('Detection methods, alarm decision logic, evidence ranking and TDOA suitability', SUB))
    s.append(P('Source: static analysis of tsukor_s3v4_5.5.12_en.bin (Ghidra 11.4.2, Xtensa) and the AMICCOM A5133 datasheet v0.7. '
               'Full addresses and raw constants are in research/briefs/tsukorok-firmware-5.5.12-rf-extraction.md. '
               'Values marked CONFIRMED were read from bytes or disassembly; INFERRED means reasoned from behaviour. '
               '"TDAO" in the request is read as TDOA (time difference of arrival localisation); if a different system was meant, section 5 must be re-read.', S))
    s.append(Spacer(1, 6))

    s.append(P('1. What the device is', H1))
    s.append(P('An ESP32-S3 handheld with three receivers driven by RadioLib and a bit-banged driver: an SX1280 for 2.4 GHz, an SX1276/SX1278 for '
               '860-1020 MHz, and an AMICCOM A5133 for 5.8 GHz. No protocol is decoded anywhere. Every alarm is produced either from RSSI '
               'sweeps (energy morphology) or from the first 32-bit word received after an FSK preamble ("syncword"). In AERIX RF terms every '
               'output is stage-1 (RF candidate/morphology) or stage-2 (probabilistic classification) evidence.'))
    s.append(P('One caveat for anyone using it as a reference receiver: the 5.8 GHz driver issues the A5133 TX-mode strobe (0xD8) to leave RX '
               'before each RSSI read and holds TX mode for 10 ms at every scan start and before calibration. Whether that radiates has not '
               'been measured, but the device should not be assumed silent at 5.8 GHz.'))

    s.append(P('2. Detection methods and the yes/no alarm rule', H1))
    s.append(P('Each row gives the radio, what is measured, the exact decision, and the label the device shows. Thresholds are the firmware defaults.', S))
    rows = [['#', 'Method (radio)', 'What is measured', 'Alarm = YES when', 'Label / type'],
     ['A1', 'Sub-GHz FSK static syncword (SX127x)',
      'FSK RX at 57.6 / 80 / 15.235 kbps, 100 kHz steps over 860-885 / 895-928 / 970-1020 MHz. First 32-bit word after preamble, normalised, looked up in a 9-entry table.',
      'Word (or its shifted/normalised form) matches the table AND corrected RSSI &ge; -94 dBm (rssi_threshold 188 / 2). One packet is enough.',
      'Or (Orlan class), Za (Zala), ZL (ZalaLancet), El (ELRS-like)'],
     ['A2', 'Sub-GHz syncword-count (learned)',
      'Same packets; every new word is stored with frequency, bitrate, time (entries expire after 20 min).',
      'Same word seen again: count &ge; 2 on 865-872 or 902-928 MHz with a second such word in the band &rarr; ZL; same word on both bands at 15.235 kbps &rarr; Lc; at 84.6-85.6 kbps in 860-885 or 902-922 MHz &rarr; ?FPV; at 15.235 kbps above 970 MHz &rarr; Sc. Plus the RSSI gate.',
      'ZL, Lc, ?FPV, Sc; otherwise "*" (unknown FSK, type 1)'],
     ['A3', '"cryptoorlan" (learned, 55.0-58.0 kbps only)',
      'Words that differ on every packet at ~57.6 kbps on one frequency.',
      'More than 3 distinct words stored AND more than 3 of them seen exactly once (i.e. &ge;4 different words at one frequency), packet RSSI arg &gt; 30.',
      'X3 (type 10)'],
     ['B1', 'Sub-GHz LoRa / ELRS mode 1 (SX127x CAD)',
      'Per 125 kHz channel: RSSI gate, then LoRa channel-activity detection at SF6-9 with 500 kHz BW for 50 ms; if two CAD hits at one SF, receive 8 bytes and read SNR.',
      'At the end of the range: max RSSI &ge; -199 (always) AND 6&middot;good + 3&middot;bad + timeouts &ge; 6 AND the dominant SF was hit more than {SF6:5, SF7:8, SF8:5, SF9:4} times.',
      '"Lora detected" match callback (ELRS-like)'],
     ['B2', 'Sub-GHz LoRa mode 2',
      'Same, single SF (sf_first = 9), 2-3 passes.',
      '6&middot;good + 3&middot;bad &ge; 6 AND (good &ge; 1 OR bad &ge; 2).',
      'same'],
     ['C1', '2.4 GHz DJI spectral score A (SX1280)',
      '8 sweeps of 256 bins (390.625 kHz) over 2400-2500 MHz. Segments above median+5 dB, features: width, mean-median, flatness, persistence over sweeps.',
      'Score = 0.55&middot;s1 + 0.45&middot;s2 &gt; 40 (of 100). Width ideal 39 bins (~15 MHz), accepted 26-52 bins; persistence in &ge;3 of 8 sweeps.',
      'DJI (type 13) or DJIe (type 18, width &gt; 80 bins)'],
     ['C2', '2.4 GHz DJI spectral score B',
      'Same spectrum; segments 18-60 bins wide, gap merge 3, persistence &ge;3 sweeps with &ge;2 bins, &ge;85 % of cells above threshold, &le;40 % always-on bins, centre-edge margin 5 dB.',
      'Score &gt; 3.14. dji_alg = 2 needs A AND B, dji_alg = 3 needs A OR B.',
      'DJI / DJIe'],
     ['C3', '2.4 GHz DJI candidate + time-domain (dji_alg = 1, default)',
      'Candidates: bins above 40th-percentile+6 dB in &ge;2 sweeps, width 20-102 bins. For each candidate 8192 RSSI samples on two channels (start+w/3, end-w/3).',
      'Both traces classified "periodic bursts": duty 0.3-0.9, max gap &le; 750 samples, &lt;3 short bursts (32-75 samples), &ge;5 long bursts and gaps (&ge;64 samples), modal burst/gap length (20-sample buckets) repeats &ge;5/&ge;3 times, top buckets cover &ge;50 %.',
      'DJI / DJIe'],
     ['C4', '2.4 GHz "paranoid" sweep (dji_alg = 4)',
      '250 channels x 400 kHz, 40 &micro;s settle, threshold dji_rssi_thrsh -95 dBm; 16-sample sliding window.',
      '&ge;8 of the last 16 channels above threshold (&ge;3.2 MHz) AND fewer than 125 of 250 channels above threshold, accumulated over sweeps: +1/-1 per sweep, clamp 0-4, alarm when accumulator &gt; 1.',
      'DJI'],
     ['C5', '2.4 GHz Zala video sweep (detect_zl_la = 2)',
      '500 channels x 400 kHz from 2200 MHz, 60 &micro;s settle, threshold -94 dBm.',
      '&ge;7 of 16 consecutive channels above threshold AND fewer than 250 above; accumulator clamp 0-3, alarm when &gt; 1.',
      'ZalaV (type 2)'],
     ['C6', '"Skydio" metric (skydio_alg 1-4)',
      'Histogram of the 3-dB-quantised RSSI levels above -90 dBm in the 8x256 spectrum.',
      'Count of the most frequent level &gt; 70 gives 80, &gt; 50 gives 60, &gt; 30 gives 40; alarm if that value &ge; {70,60,50,40}[skydio_alg].',
      'Skydio (type 5)'],
     ['D1', '5.8 GHz A5133 paranoid sweep (dji_alg = 4)',
      '175 channels x 1 MHz, 5725-5899 MHz, RSSI = ((ADC-RL)/(RH-RL))&middot;12 - 83 dBm, threshold -95 dBm.',
      'Same 16-window rule (&ge;8 of 16), guard &lt; 87 channels, accumulator 0-4, alarm &gt; 1; OR immediately if the 16-sample window shows a rise-peak-fall shape (returns "dji 5.8").',
      'FPV5 / DJI 5.8 (type 3)'],
     ['D2', '5.8 GHz A5133 spectral (other dji_alg)',
      'One 175-channel sweep; thresholds from -65 dBm down to -99 in 5 dB steps.',
      'A segment 16-69 MHz wide (gap tolerance 5) whose edges stay within 5 MHz of the segment found at the previous, higher threshold (steep edges); needs two consecutive positive sweeps.',
      'FPV5 (type 3)'],
     ['E1', 'Track mode (SX1280 or A5133)',
      'f &plusmn; 10 MHz around a chosen frequency, 400 kHz (2.4 GHz) or 1 MHz (5.8 GHz) steps, two passes.',
      'More than 10 samples above threshold.',
      'Track f=... r=...'],
     ['E2', 'RSSI scan / unknown drone (SX127x)',
      'RSSI sweep of the configured range at 100 kbps FSK, +15 dB correction if &gt;30 % of channels read below -112 dBm.',
      'Peak &gt; -rssi_scn_tresh (-60 dBm).',
      'Unknown'],
    ]
    s.append(tbl(rows, [9*mm, 30*mm, 44*mm, 58*mm, 29*mm]))
    s.append(Spacer(1, 6))
    s.append(P('Common gate for every sub-GHz alarm: a packet only counts if RSSI (after the +15 dB noise correction) is at least -(rssi_threshold/2) = -94 dBm; '
               'below that it is logged as "below threshold" and discarded. All 2.4/5.8 GHz alarms are rate-limited to one per type per 3 s.', S))

    s.append(P('3. Pseudocode of the two decision cores', H1))
    s.append(P('Sub-GHz FSK packet (IRAM FSK_MatchOnPacket):', H2))
    s.append(P('rssi = read_rssi(); if noise_flag: rssi += 15<br/>'
               'hits = [static_table(word), sync_count(word, f, br), cryptoorlan(word, f, br, rssi)]<br/>'
               'if hits empty: log "candidate f, br"        # stage-1 only, no alarm<br/>'
               'elif rssi &lt; -(rssi_threshold &gt;&gt; 1): log "below threshold"<br/>'
               'else: alarm(label(hits, br), f, rssi)      # one packet suffices', C))
    s.append(P('2.4 / 5.8 GHz tick (IRAM TwoFourGScanner_Tick, at most every 5 s):', H2))
    s.append(P('if dji_alg == 4: det = paranoid_sweep()<br/>'
               'else: spec = 8 sweeps x 256 bins<br/>'
               '      A = scoreA(spec) &gt; 40 ; B = scoreB(spec) &gt; 3.14<br/>'
               '      dji_alg 2: det = A and B ; 3: det = A or B<br/>'
               '      dji_alg 1: det = any(candidate c: burst_classify(td(c.start+w/3)) and burst_classify(td(c.end-w/3)))<br/>'
               '      if not det and skydio_alg: det = noise_level(spec) &ge; table[skydio_alg]<br/>'
               'if not det and detect_zl_la == 2: zala = zala_sweep()<br/>'
               'if not zala and a5133: r = a5133_sweep(); five8 = (r == 2); det |= (r != 0)<br/>'
               'emit(type 3 if five8 else 2 if zala else 1/5) unless same type within 3000 ms', C))

    s.append(P('4. Ranking by evidence value', H1))
    s.append(P('Ranked by how far the rule is from "there is energy here" towards a system-specific fingerprint, and by the false-alarm exposure of the rule. '
               'This is an assessment (INFERRED), the thresholds are CONFIRMED.', S))
    rank = [['Rank', 'Method', 'AERIX RF evidence level', 'Why'],
     ['1', 'A1 static syncword + bitrate/band', 'Level 3 candidate (protocol-specific evidence) if the nine words are genuine; until verified, level 2',
      'A 32-bit word after a preamble at a specific bitrate in a specific band is a real fingerprint. Weakness: the words come from the vendor, are not validated in the image, and a single packet fires the alarm.'],
     ['2', 'A2 syncword-count with band rules', 'Level 2',
      'Repetition of the same unknown word on the same channel is strong evidence of a real digital link; the band/bitrate rules add plausibility but the "which drone" labels are heuristic.'],
     ['3', 'B1 LoRa CAD + SNR (ELRS-like)', 'Level 2',
      'CAD at SF6-9/500 kHz plus a positive-SNR packet is a good LoRa-presence test; it does not distinguish ELRS from other LoRa users.'],
     ['4', 'A3 cryptoorlan', 'Level 2, high false-alarm exposure',
      'Four different words at ~57.6 kbps is consistent with an encrypted/whitened link but also with any noisy FSK demodulation; keep as supporting evidence only.'],
     ['5', 'C3 candidate + time-domain bursts', 'Level 1-2',
      'Combines width with burst periodicity; the best of the 2.4 GHz rules, but the periodicity test is coarse (20-sample buckets, no timing reference).'],
     ['6', 'C1 / C2 spectral scores', 'Level 1',
      'Width, flatness and persistence of a 7-23 MHz block. Wi-Fi, video links and other OFDM users share this morphology.'],
     ['7', 'D2 5.8 GHz spectral (steep edges)', 'Level 1',
      'A steep-edged 16-69 MHz block in 5.8 GHz is typical of analog/digital FPV video; not specific.'],
     ['8', 'C4 / C5 / D1 paranoid sweeps, E1 track', 'Level 1',
      'Pure occupancy counting in a 16-channel window. The broadband guards only reject jamming-like saturation.'],
     ['9', 'C6 "Skydio" metric, E2 RSSI scan', 'Below level 1',
      'A histogram of RSSI levels or a peak above -60 dBm says nothing about the source.']]
    s.append(tbl(rank, [11*mm, 40*mm, 44*mm, 75*mm]))

    s.append(P('5. Usability for TDOA', H1))
    s.append(P('TDOA needs the same emission time-stamped at three or more receivers with a common clock, at a precision of tens of nanoseconds '
               '(300 m of range difference per microsecond). Judged against that:'))
    s += bullets([
        '<b>None of the device\'s own detection outputs are TDOA-usable.</b> They are RSSI sweeps with 40-300 &micro;s settle times and 5 s tick '
        'periods, or packet events time-stamped by <i>millis()</i> on an unsynchronised ESP32. There is no IQ, no sample clock, no GPS-disciplined time.',
        '<b>The signals it exploits are TDOA-usable with SDRs.</b> Sub-GHz FSK packets with a fixed preamble and a repeating 32-bit word (A1/A2) '
        'give a correlation peak that can be time-stamped at the sample level; ELRS LoRa packets (B1) likewise via chirp correlation; DJI '
        'OcuSync bursts (C-methods) are wide, short and periodic and are the classic TDOA target. What is needed is coherent, GPS-disciplined '
        'receivers such as the ANTSDR E200 with a common reference, not this device.',
        '<b>What can be reused:</b> the frequency plans, bitrates and syncwords as <i>where to correlate</i>; the burst-periodicity idea (C3) as a '
        'gate before spending TDOA correlation effort; the DJI width window as a candidate filter.',
        '<b>RSSI-only alternative:</b> the device\'s outputs could feed RSSI-based ranging or direction-by-comparison across several units, '
        'which is not TDOA and is far less accurate (&plusmn;6 dB RSSI on the A5133 alone).'])
    s.append(Spacer(1, 4))
    s.append(P('Summary: use the firmware as a catalogue of heuristics and target signatures; use the E200/HackRF chain for anything that must be timed.', B))
    doc.build(s, onFirstPage=footer, onLaterPages=footer)

# ------------------------------------------------------------------ Document B
def doc_b(path):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title='Replicating the Tsukorok receiver chain - hardware and development boards', author='AERIX RF research')
    s = []
    s.append(P('Replicating the Tsukorok receiver chain', T))
    s.append(P('Hardware and development boards (receive-only replication; AERIX RF policy excludes any transmit use)', SUB))
    s.append(Spacer(1, 6))
    s.append(P('1. What the original uses (CONFIRMED from firmware)', H1))
    hw = [['Block', 'Part', 'Bus / pins in firmware', 'Notes'],
     ['MCU', 'ESP32-S3 (Xtensa LX7), Arduino-ESP32 / ESP-IDF 4.4.7', '-', 'Wi-Fi, OLED, buzzer, SPIFFS captures, CLI'],
     ['2.4 GHz', 'Semtech SX1280 (RadioLib SX128x)', 'SPI SCK17 MISO15 MOSI16 NSS18, IRQ14 RST12 BUSY13, 2 MHz', 'Used in FSK mode 250 kbps/195 kHz for RSSI sweeps, LoRa 812.5 kHz for the ELRS scan'],
     ['Sub-GHz', 'Semtech SX1276/SX1278 (RadioLib SX127x)', 'SPI SCK7 MISO6 MOSI8 NSS9, 10 MHz, DIO0 ISR', 'FSK 15-80 kbps, 76.7 kHz dev, 200 kHz RX BW; LoRa 500 kHz CAD; 755 MHz init, sweeps 860-1020 MHz'],
     ['5.8 GHz', 'AMICCOM A5133 (bit-banged 3-wire SPI)', 'SDIO16 SCK17 CS48 (shares 16/17 with the SX1280 bus)', '5725-5899 MHz in 1 MHz steps, 8-bit RSSI. Rarely stocked outside Asia'],
     ['2.4 GHz alt.', 'TI CC2500', 'present, "cc2500 unsupported" for scans', 'legacy path, not needed'],
     ['Power', 'GPIO21 RF section enable', '-', 'radios powered only during a tick']]
    s.append(tbl(hw, [20*mm, 45*mm, 55*mm, 50*mm]))

    s.append(P('2. Development boards that replicate it', H1))
    s.append(P('Everything below is receive-capable with RadioLib on ESP32-S3; transmit functions are simply never called. Prices are indicative.', S))
    boards = [['Option', 'Boards / modules', 'Covers', 'Comment'],
     ['Closest one-board match', 'LilyGO T3-S3 (ESP32-S3 + radio + OLED), available with SX1280 (2.4 GHz LoRa) or SX1276/SX1262 (sub-GHz)',
      '2.4 GHz OR sub-GHz per board', 'Two T3-S3 boards (one SX1280, one SX1276) reproduce the SX-radio parts almost pin-for-pin in spirit; RadioLib examples exist for both.'],
     ['Modular build', 'ESP32-S3-DevKitC-1 (N8R8) + Ebyte E28-2G4M12S/E28-2G4M27S (SX1280) + HopeRF RFM95W/RFM96W or Ebyte E19-868M30S (SX1276)',
      '2.4 GHz + 860-1020 MHz', 'Choose the 868/915 MHz SX1276 variant (RFM95/96), not the 433 MHz SX1278 modules (Ra-01/02) - the sweeps go to 1020 MHz. SX1276 tunes 137-1020 MHz.'],
     ['Heltec alternative', 'Heltec WiFi LoRa 32 V3 / LilyGO T-Beam (SX1262)',
      'sub-GHz', 'SX1262 is not the same chip; RadioLib supports it, but the CAD/receive-fast register tricks of the firmware are SX127x-specific and would need re-implementation.'],
     ['5.8 GHz, faithful', 'AMICCOM A5133 module (vendor modules from Taiwan/China; part is 5.8 GHz 15 dBm FSK, 3/4-wire SPI)',
      '5725-5899 MHz', 'Hard to source; and note the firmware\'s TX-strobe misuse - a replication must use Standby/PLL strobes (0xA0/0xB0) to leave RX.'],
     ['5.8 GHz, practical', 'RX5808 / RTC6715 analog video receiver module with RSSI pin, SPI-tunable (5645-5945 MHz)',
      '5.8 GHz RSSI sweeps', 'Receive-only by design, cheap, widely used with ESP32 in FPV diversity projects. Reproduces D1/D2 style sweeps (RSSI vs channel), not FSK reception.'],
     ['Full-band SDR', 'HackRF One (1 MHz-6 GHz, 20 MS/s) - already the AERIX RF secondary backend',
      'all three bands', 'Reproduces every sweep as a spectrum, and adds what the device lacks: IQ, syncword correlation, timing. Not real-time for the packet-level FSK receive unless a demodulator is implemented.'],
     ['Primary platform', 'ANTSDR E200 (AD9361, 70 MHz-6 GHz, 2x2)',
      'all three bands, coherent', 'The only option here that supports TDOA-grade timing (with GPSDO/reference). Use it to validate the syncwords and to measure the Tsukorok\'s own 5.8 GHz emissions.']]
    s.append(tbl(boards, [28*mm, 58*mm, 28*mm, 56*mm]))

    s.append(P('3. Recommended replication plan', H1))
    s += bullets([
        '<b>Step 1 - sub-GHz FSK/LoRa (highest-value methods A1/A2/B1):</b> ESP32-S3 + SX1276 module (RFM95W or E19-868M30S), RadioLib, '
        'beginFSK(755 MHz, br/1000, 76.7 kHz, 200 kHz, 10 dBm, preamble 16) then sweep with setFrequency/setBitRate exactly as the firmware does; '
        'log the first 4 bytes after preamble. Compare against the nine static words.',
        '<b>Step 2 - 2.4 GHz spectral:</b> second board or a T3-S3 SX1280; FSK 250 kbps, 400 kHz steps, GetRssiInst. Implement the 16-window and the '
        'score-A/B features from the brief; expect the same false alarms on Wi-Fi.',
        '<b>Step 3 - 5.8 GHz:</b> RX5808 with RSSI to ADC for the sweep-based rules; skip the A5133 unless a module is available, and never use TX strobes.',
        '<b>Step 4 - cross-check with the SDRs:</b> capture the same bands with HackRF/E200 while the replica runs; this is what upgrades vendor '
        'syncwords from level 2 to level 3 evidence and what a TDOA experiment needs anyway.'])
    s.append(Spacer(1, 4))
    s.append(P('Cost indication: two T3-S3 boards plus an RX5808 module is under 100 EUR; the SDR chain already exists in the project.', S))
    doc.build(s, onFirstPage=footer, onLaterPages=footer)

doc_a('/tmp/claude-0/-home-user-AerixRF/98dca1bc-ab87-5670-a541-080b7016c718/scratchpad/Tsukorok_5.5.12_detection_methods_summary.pdf')
doc_b('/tmp/claude-0/-home-user-AerixRF/98dca1bc-ab87-5670-a541-080b7016c718/scratchpad/Tsukorok_replication_hardware.pdf')
print('ok')
