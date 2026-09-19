"""Generate the AERIX01 receiver-module project description + Program of Requirements PDF.

Source of truth for the content: 00-common-slot-interface.md, 01-subghz-sx1276-module.md,
02-2g4-sx1280-module.md, 03-5g8-rx5808-module.md in this directory. Run:

    python3 docs/hardware/modules/make_por_pdf.py
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether)

OUT = 'docs/hardware/modules/AERIX01_receiver_modules_project_description_and_PoR.pdf'
VERSION = '0.1'
DATE = '2026-09-19'

styles = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=15, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor('#1a3c5a'))
H2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=12, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor('#1a3c5a'))
B = ParagraphStyle('B', parent=styles['Normal'], fontSize=9.2, leading=12.5)
S = ParagraphStyle('S', parent=B, fontSize=8, leading=10.5)
C = ParagraphStyle('C', parent=B, fontName='Courier', fontSize=7.8, leading=10, leftIndent=8, backColor=colors.HexColor('#f3f5f7'))
T = ParagraphStyle('T', parent=styles['Title'], fontSize=18, spaceAfter=4)
SUB = ParagraphStyle('SUB', parent=B, textColor=colors.HexColor('#555555'))


def P(t, st=B):
    return Paragraph(t, st)


def bullets(items, st=B):
    return [Paragraph('&bull; ' + i, ParagraphStyle('bl', parent=st, leftIndent=10, firstLineIndent=-8)) for i in items]


def tbl(rows, widths, header=True, st=S):
    data = [[Paragraph(c, st) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    ts = [('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#9aa5b1')),
          ('VALIGN', (0, 0), (-1, -1), 'TOP'),
          ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
          ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]
    if header:
        ts += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dfe7ef'))]
    t.setStyle(TableStyle(ts))
    return t


def req(rows):
    """Requirement table: ID, requirement, verification, priority (M/S/C)."""
    return tbl([['ID', 'Requirement', 'Verification', 'Prio']] + rows, [16*mm, 96*mm, 46*mm, 12*mm])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(colors.HexColor('#666666'))
    canvas.drawString(20*mm, 10*mm, doc.title + '  v' + VERSION + '  ' + DATE)
    canvas.drawRightString(190*mm, 10*mm, 'page %d' % doc.page)
    canvas.restoreState()


def build(path):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm,
                            title='AERIX01 receiver modules - project description and Program of Requirements',
                            author='AERIX RF')
    s = []
    s.append(P('AERIX01 receiver modules', T))
    s.append(P('Project description and Program of Requirements (PoR) for three plug-in receiver modules and one base-board change', SUB))
    s.append(P(('Version %s, %s. ' % (VERSION, DATE)) + 'Status: draft for the hardware designer. Normative detail lives in the four Markdown specifications in '
               '<font face="Courier">docs/hardware/modules/</font> (00-common, 01-subghz, 02-2g4, 03-5g8); where this PDF and those files '
               'disagree, the Markdown files win and this PDF must be regenerated (make_por_pdf.py). '
               'Priority codes: M = must (acceptance blocker), S = should (deviation needs project-lead sign-off), C = could (nice to have).', S))
    s.append(Spacer(1, 6))

    # ------------------------------------------------------------ PART 1
    s.append(P('Part 1 - Project description', H1))

    s.append(P('1.1 Why this project exists', H2))
    s.append(P('AERIX RF is a passive, receive-only drone-detection system. Its primary receiver is a software-defined radio (ANTSDR E200) '
               'that captures IQ data around 2.4 GHz and runs energy-morphology, classification and DroneID decoding on a Linux host. '
               'That path is deep but narrow: one SDR looks at one band segment at a time, and it costs host CPU and USB bandwidth.'))
    s.append(P('A static analysis of a commercial handheld detector (Tsukorok S3 v4, firmware 5.5.12) showed that a large part of the practical '
               'coverage - sub-GHz FSK/LoRa control links (Orlan/Zala/Lancet-class and ELRS-class), 2.4 GHz wideband persistence, and 5.8 GHz '
               'video/DJI-class occupancy - is obtained with three cheap narrowband radios doing RSSI sweeps and preamble-triggered packet '
               'capture. Those radios (SX127x, SX128x, a 5.8 GHz RSSI receiver) draw about 100-250 mA, need no IQ processing and can run '
               'continuously and in parallel.'))
    s.append(P('This project adds that coverage to the AERIX01 sensor as three plug-in modules, one per band, sitting in the spare MCU slots of the '
               'existing AERIX01 V1 base board. The goal is not to copy the handheld: the modules report far more than alarms (every packet '
               'above a gate, full sweeps, occupancy statistics) so that the always-online server can build per-sensor baselines, whitelists and '
               'ODID-labelled training data. The handheld\'s thresholds become configurable starting points, not the decision.'))

    s.append(P('1.2 System context', H2))
    s.append(tbl([
        ['Element', 'Role in this project'],
        ['AERIX01 V1 base board', 'Existing. MAIN ESP32-S3 = system controller (also keeps Wi-Fi/BLE scanning). AUX ESP32-S3 slot, two ESP32-C5 slots, '
         'USB2517 hub (upstream USB-C to the Linux host), W5500 Ethernet with PoE, MAX-M10S GNSS with TIMEPULSE, mini-PCIe LTE modem.'],
        ['Module 1 - Sub-GHz', 'SX1276, 860-1020 MHz. FSK packet capture after preamble (first 4 bytes = "word"), LoRa CAD, 100 kHz RSSI sweeps. Highest value.'],
        ['Module 2 - 2.4 GHz', 'SX1280, 2400-2500 MHz (2200-2400 to be verified). 400 kHz RSSI sweeps at 1 sweep/s, DJI-class scoring as candidates, ELRS-2.4 LoRa CAD/packets.'],
        ['Module 3 - 5.8 GHz', 'RX5808 / RTC6715, 5645-5945 MHz. Analog-RSSI sweeps (slow, ~6 s), steep-edge candidates for FPV-video/DJI-5.8 class.'],
        ['MAIN S3', 'Collects the three module UART streams, time-stamps against GNSS, forwards over Ethernet/PoE (LTE fallback with reduced classes).'],
        ['Linux host (on-board)', 'Runs the SDR path; optionally takes bulk traces from the modules over USB (class G).'],
        ['Server', 'Baselines, whitelists, differencing between sensors, ODID-labelled learning, final alarm decision. Owns the word tables and thresholds.'],
    ], [38*mm, 132*mm]))
    s.append(Spacer(1, 4))
    s.append(P('Data flow: module radio &rarr; module ESP32-S3 (scan loop, gate, candidate rules) &rarr; UART 921 600 baud &rarr; MAIN S3 '
               '(UTC time from GNSS PPS, credits) &rarr; Ethernet &rarr; server. Bulk traces: module USB &rarr; hub &rarr; host. '
               'Every record carries the PPS count and microseconds since the last PPS edge, so bursts seen by different modules and different '
               'sensors can be matched to about 1 µs.'))

    s.append(P('1.3 Scope and deliverables', H2))
    s.append(P('In scope:', B))
    s += bullets([
        'Three module PCBs (schematic, layout, BOM, assembly drawing, test-pad map) in the existing C5-module outline, interchangeable between the two C5 slots and the AUX slot.',
        'One base-board change on AERIX01 V1: GNSS TIMEPULSE routed to one pin of each receiver slot (0 &Omega; options on the module side).',
        'Firmware per module (ESP-IDF, RadioLib, TinyUSB) implementing the scan plans, candidate rules, the UART/USB data contract and the receive-only lock-out.',
        'MAIN S3 firmware extension: three UART collectors, credit flow control, CFG/TIME distribution, Ethernet forwarding, LTE class masking.',
        'Acceptance test procedure and first-article test report per module (Part 2, section T).',
    ])
    s.append(P('Out of scope (do not design for):', B))
    s += bullets([
        'Any transmit, jamming, spoofing, ranging, CAD-then-TX or active interrogation. The modules are receive-only by firmware; TX paths are never initialised and the acceptance test checks the antenna port for emissions.',
        'Replacing the SDR path: the modules deliver RSSI and demodulated packet heads, no IQ.',
        'Protocol decoding on the module. Output is stage-1 (RF morphology) and stage-2 (probabilistic) evidence; the server and the SDR path own anything above that.',
        'FPGA acceleration, a new base board, or changing the MAIN S3 role.',
    ])

    s.append(P('1.4 Decisions already taken', H2))
    s.append(tbl([
        ['Topic', 'Decision'],
        ['Slots', 'Two ESP32-C5 slots + AUX S3 slot carry the modules; MAIN S3 stays controller. AUX slot conflicts with LTE control (see risks).'],
        ['Base board', 'V1 as built, plus the PPS trace to the slots.'],
        ['Module MCU', 'ESP32-S3 with PSRAM (WROOM-1-N8R8 or bare chip + 8 MB flash + 8 MB PSRAM). Wi-Fi/BLE disabled in firmware.'],
        ['Radios', 'SX1276 (not SX1278), SX1280/SX1281, RX5808 (RTC6715) with SPI mod. No A5133 (the handheld\'s 5.8 GHz part is likely unpopulated and its driver toggles TX mode).'],
        ['Data path', 'UART to MAIN S3 for classes A-F; USB to host for class G bulk.'],
        ['Uplink', 'Ethernet/PoE, tens of kB/s per sensor available; LTE fallback profile masks classes C and E.'],
        ['TX lock-out', 'Firmware-only (standard radio wiring, TX never initialised, compile-time RX-only flag, image grep test, emission test).'],
        ['Sub-GHz band', '860-1020 MHz.'],
        ['Diagnostic set', 'Raw packet heads (32/64 B), full RSSI sweeps, per-channel occupancy; receiver health as low-priority extra.'],
        ['"Enough" data', 'All classes A-F at urban worst-case rate simultaneously with 3x link headroom: about 3 kB/s per module vs about 90 kB/s at 921 600 baud.'],
    ], [32*mm, 138*mm]))

    s.append(P('1.5 Evidence policy (applies to every field name and every alarm)', H2))
    s.append(P('AERIX RF distinguishes five evidence levels: (1) RF candidate / morphology, (2) probabilistic classification, (3) protocol-specific evidence, '
               '(4) validated deterministic decode, (5) operator-provided truth. The modules produce level 1 and 2 only. A module ALARM is a '
               '"detector verdict", not a confirmed drone; the server may downgrade it. The firmware and the documentation must not label an RSSI '
               'shape or a repeated word as a drone type without the level attached. Whitelisting (5 GHz Wi-Fi channels 149-165 inside the 5.8 GHz '
               'band, LoRaWAN/Meshtastic on sub-GHz, Wi-Fi blocks at 2.4 GHz) is done on the server; the module only flags.'))

    s.append(P('1.6 Risks and open items for the designer', H2))
    s.append(tbl([
        ['#', 'Item', 'Owner / how to close'],
        ['R1', 'AUX slot vs LTE: the AUX S3 owns the modem UART/control lines. A module in that slot removes LTE unless the modem is driven from MAIN S3 in firmware.',
         'Designer confirms which nets the AUX slot header carries; project lead decides per site (2 or 3 modules).'],
        ['R2', 'RX5808 supply: 180-200 mA for the receiver plus ~60 mA ESP32 sits at the 250 mA slot budget; the base ferrite (120 &Omega; @ 100 MHz) DC rating must be >= 500 mA.',
         'Designer checks FB10/FB11 rating and 3V3 rail budget; fallback is the AUX slot or an RTC6712/6715 board with lower current.'],
        ['R3', 'SX1280 below 2400 MHz (raster B, 2200-2400 MHz) is out of datasheet range; the handheld does it anyway.',
         'Bench measurement on the first article; if RSSI accuracy is unacceptable, raster B is dropped and flagged in HELLO capabilities.'],
        ['R4', 'Sub-GHz antenna: most 868/915 whips roll off above 930 MHz; the plan covers 970-1020 MHz.',
         'Antenna selection note; wideband or dedicated antenna for the upper range.'],
        ['R5', 'PPS position on the AUX slot header may differ from the C5 slots.',
         'Designer verifies the netlist; 0 &Omega; options R_PPS_A/B and R_BOOT_A/B on the module.'],
        ['R6', 'USB 2.0 hub upstream is shared by everything on the board; class G bulk must not starve the SDR path.',
         'Host throttles class G (module never pushes unrequested bulk).'],
        ['R7', 'ESP32-S3 40 MHz clock harmonics (60 x 40 MHz = 2400 MHz) on the 2.4 GHz module.',
         'Layout: ESP32 at the far end from the u.FL, shield can, sensitivity test with the scan loop running.'],
    ], [10*mm, 90*mm, 70*mm]))

    s.append(P('1.7 Phasing', H2))
    s.append(tbl([
        ['Phase', 'Content', 'Exit criterion'],
        ['0 Design review', 'Designer reviews the four Markdown specs + this PoR, returns questions and the AUX/RX5808/PPS netlist answers (R1, R2, R5).', 'Open items R1, R2, R5 closed in writing.'],
        ['1 Schematic + layout', 'Three modules, base-board PPS ECO. Test pads per spec.', 'Design review against Part 2 sections M, E, I.'],
        ['2 First article', 'Two units per module type, hand-assembled or small batch.', 'Fit in all three slots; enumerates; boots; HELLO on UART.'],
        ['3 Firmware bring-up', 'Scan plans, data classes, PPS timestamping, RX-only build; MAIN S3 collector.', 'Common tests T-01..T-06 pass; module tests pass on the bench.'],
        ['4 Field pilot', 'One sensor with all three modules online for >= 2 weeks in an urban site; server collects classes A-F.', 'Baseline/occupancy data usable; false-alarm rate report; go/no-go for batch.'],
    ], [30*mm, 85*mm, 55*mm]))

    s.append(PageBreak())

    # ------------------------------------------------------------ PART 2
    s.append(P('Part 2 - Program of Requirements', H1))
    s.append(P('Each requirement has an ID (section letter + number), a verification method and a priority. Numeric values are the defaults '
               'from the Markdown specifications; "CFG" means the value is a runtime configuration item owned by the MAIN S3/server.', S))

    s.append(P('G - General', H2))
    s.append(req([
        ['G-01', 'The modules are receive-only. No transmit, ranging, CAD-then-TX, beacon or interrogation function of any radio may be enabled in hardware or firmware.', 'Design review; T-06 emission test; firmware image grep for TX entry points.', 'M'],
        ['G-02', 'Three module types: Sub-GHz (SX1276), 2.4 GHz (SX1280/1281), 5.8 GHz (RX5808/RTC6715). One PCB design per type.', 'BOM review.', 'M'],
        ['G-03', 'A module of any type fits and functions in either ESP32-C5 slot and in the AUX ESP32-S3 slot of AERIX01 V1 without rework other than 0 &Omega; option resistors.', 'T-01 slot fit.', 'M'],
        ['G-04', 'All module output is tagged with evidence level 1 or 2; no field or document may present a module alarm as a confirmed drone.', 'Documentation and protocol review.', 'M'],
        ['G-05', 'Default thresholds and scan plans reproduce the reference handheld (firmware 5.5.12 extraction brief) where stated, but every one of them is a CFG item.', 'Firmware review; CFG round-trip test.', 'M'],
        ['G-06', 'Deliverables per module: schematic, layout, BOM, assembly drawing, test-pad map, first-article test report against section T.', 'Document check at hand-over.', 'M'],
    ]))

    s.append(P('M - Mechanical', H2))
    s.append(req([
        ['M-01', 'Outline, mounting and header positions identical to the existing ESP32-C5 module drawing (designer holds the master outline).', 'Overlay of the two outlines; T-01.', 'M'],
        ['M-02', 'Headers: two 1x12 2.54 mm and two 1x4 2.54 mm, base side PPTC121LFBN-RC and 61300411821, same positions as the C5 module.', 'Layout check.', 'M'],
        ['M-03', 'One u.FL (IPEX MHF1) at the same corner as the existing modules; 50 &Omega; ground-stitched microstrip, <= 15 mm from the radio pin to the connector.', 'Layout check; TDR or return-loss spot check on first article.', 'M'],
        ['M-04', 'Shield can over the radio section (radio + match + filter) on the Sub-GHz and 2.4 GHz modules; ground fence around the RSSI/ADC trace on the 5.8 GHz module.', 'Layout check.', 'M'],
        ['M-05', 'Height envelope as the existing module (shield can + u.FL). No components on the base-board side of the module.', 'Mechanical check in all three slots.', 'M'],
        ['M-06', 'Silkscreen: module type, revision, slot mark "C5/AUX".', 'Visual.', 'S'],
        ['M-07', 'Test pads: SCK/MISO/MOSI/NSS and DIO0 (SX modules), RSSI analog (5.8 GHz), GPIO0, EN, UART TX/RX, PPS, 3V3, GND.', 'Layout check.', 'S'],
    ]))

    s.append(P('E - Electrical and power', H2))
    s.append(req([
        ['E-01', 'The module uses only these base-side nets: 3V3 (left 1x12 pin 12), EN (left pin 10), GND (left pins 1 and 6, USB 1x4 pins 1 and 4), UART0 TX/RX (right 1x12 pins 10/9), BOOT (right pin 3 via 0 &Omega;), USB D-/D+ (USB 1x4 pins 2/3), PPS (right pin 6 via 0 &Omega;). Every other header pin is no-connect on the module.', 'Netlist review against the base board for all three slots.', 'M'],
        ['E-02', 'Where BOOT or PPS positions differ between the C5 and AUX slots, 0 &Omega; option resistors (R_BOOT_A/B, R_PPS_A/B) select the position so one PCB serves all slots.', 'Netlist review.', 'M'],
        ['E-03', 'Supply: single 3V3 through the base ferrite. No back-feed of 5 V; no draw from USB VBUS; VBUS sense only via a divider for connect detection.', 'Schematic review; T-02.', 'M'],
        ['E-04', 'Current: <= 250 mA average while scanning, <= 500 mA for 10 ms peaks (including boot inrush).', 'T-02 current measurement.', 'M'],
        ['E-05', 'Decoupling: 10 µF + 100 nF at the module supply input; radio on a separate LDO or filtered branch with >= 40 dB rejection at 100 kHz-10 MHz (3.3 V to 3.0 V LDO acceptable where the radio allows).', 'Schematic review; T-03 sensitivity with the scan loop running.', 'M'],
        ['E-06', 'EN: 10 k&Omega; to 3V3 and 1 µF to GND on the module; base RST header shorts EN to GND.', 'Schematic review.', 'M'],
        ['E-07', 'Strapping: GPIO0 on a module push button and test pad; GPIO46 low; GPIO45 low (3.3 V flash).', 'Schematic review; boot test.', 'M'],
        ['E-08', 'USB D-/D+ routed as a 90 &Omega; differential pair with an ESD diode array at the header.', 'Layout review.', 'M'],
        ['E-09', 'ESP32-S3 with >= 8 MB flash (two OTA slots) and >= 8 MB PSRAM (sweep/occupancy buffers). Wi-Fi/BLE unused; a bare chip or a WROOM with the antenna unused is acceptable; the module antenna is never shared with the ESP32.', 'BOM review.', 'M'],
        ['E-10', 'Radio reference: Sub-GHz 32 MHz TCXO ±2 ppm (crystal ±10 ppm acceptable); 2.4 GHz 52 MHz TCXO ±2 ppm (crystal ±10 ppm acceptable); TCXO preferred on both.', 'BOM review.', 'S'],
        ['E-11', 'Layout of the 2.4 GHz module places the ESP32-S3 and its 40 MHz crystal at the far end from the u.FL.', 'Layout review.', 'S'],
    ]))

    s.append(P('I - Interfaces (UART, USB, PPS)', H2))
    s.append(req([
        ['I-01', 'UART0 to the MAIN S3: 3.3 V, 921 600 baud, 8N1, no RTS/CTS; 115 200 fallback at boot, speed set by CFG.baud.', 'T-04 UART soak test.', 'M'],
        ['I-02', 'Framing: COBS with 0x00 delimiter, CRC-16/CCITT (poly 0x1021, init 0xFFFF) over the decoded payload, maximum frame 512 bytes.', 'Protocol test vectors.', 'M'],
        ['I-03', 'Flow control is credit based: the module sends at most the number of frames granted in ACK.credits and drops the lowest-priority classes first when credits are exhausted.', 'T-04 with artificial credit starvation; HEALTH counters.', 'M'],
        ['I-04', 'Frame header: u8 type, u8 seq (wrap 255), u32 t_us (µs since last PPS edge, or since boot if no PPS), u16 pps_count; fixed little-endian bodies, no strings except LOG.', 'Protocol test vectors.', 'M'],
        ['I-05', 'Message types: 0x01 HELLO, 0x02 CFG, 0x03 TIME, 0x04 ACK, 0x10 ALARM, 0x11 PACKET, 0x12 SWEEP (chunked), 0x13 OCCUPANCY, 0x14 CANDIDATE, 0x1F HEALTH, 0x20 CMD, 0x7F LOG.', 'Protocol review.', 'M'],
        ['I-06', 'Units: frequency Hz (u32), RSSI/SNR 0.25 dB steps (i16) in records, i8 dBm in sweep vectors, bitrate bps (u32), bandwidth Hz (u32), duration µs (u32).', 'Protocol review.', 'M'],
        ['I-07', 'USB: ESP32-S3 native USB (TinyUSB), self-powered; one CDC-ACM interface carrying the same framed protocol and one vendor bulk endpoint for class G. Enumeration must not depend on VBUS.', 'T-01 enumeration; host bulk test.', 'M'],
        ['I-08', 'The module runs fully on UART alone; USB is optional at runtime. Class G is sent only on host request and is throttled by the host.', 'Run with the USB pins disconnected.', 'M'],
        ['I-09', 'PPS input on GPIO4 via 0 &Omega; from right 1x12 pin 6; captured by ISR or GPTimer capture; t_us resets on each edge. Without PPS the module syncs to TIME messages (±1 ms) and flags "no PPS" in HEALTH.', 'T-05 two-module timestamp test.', 'M'],
    ]))

    s.append(P('D - Data contract ("enough")', H2))
    s.append(P('The link must carry all classes A-F at their nominal urban worst-case rate simultaneously, with 3x headroom. This is about '
               '3 kB/s per module against about 90 kB/s available; three modules use three separate UARTs on the MAIN S3.', S))
    s.append(tbl([
        ['Class', 'Content', 'Nominal rate', 'Bytes/s', 'Prio (1 = dropped last)'],
        ['A ALARM', 'type code, freq, bandwidth/bitrate, RSSI, SNR, score, fingerprint (word or hash), count, first/last time', '<= 2/s', '200', '1'],
        ['B PACKET', 'every packet above the gate: freq, bitrate/SF/BW, RSSI, SNR, frequency error, preamble length, first 32 bytes (64 on request), CRC-present flag', '20/s FSK, 5/s LoRa', '2 000', '2'],
        ['C SWEEP', 'full RSSI vector, i8 dBm: sub-GHz 1 600 pts / 5 s; 2.4 GHz 250 pts / 1 s; 5.8 GHz 175 pts / 6 s', 'per module', '320 / 250 / 30', '4'],
        ['D OCCUPANCY', 'per channel: busy fraction u8, RSSI p50/p95 i8, burst count u8; delta once per 60 s', '1/min', '<= 110', '3'],
        ['E CANDIDATE', 'stage-1 events without alarm: freq, width, duration, score, why-rejected code', '<= 5/s', '250', '3'],
        ['F HEALTH', 'noise floor per band, gain state, radio temperature, PLL lock, drop and credit-starvation counters, PPS present, fw hash', '1 / 10 s', '10', '1'],
        ['G TRACE', 'USB only: time-domain RSSI traces (e.g. 8 192 samples), long packet bodies, high-rate sweeps', 'on request', '<= 200 kB/s', 'USB'],
    ], [22*mm, 84*mm, 24*mm, 20*mm, 20*mm]))
    s.append(Spacer(1, 3))
    s.append(req([
        ['D-01', 'Every module implements classes A, C, D, E, F; the Sub-GHz and 2.4 GHz modules also implement B; the 5.8 GHz module has no B.', 'Protocol test per module.', 'M'],
        ['D-02', 'Class B is emitted for every packet above the gate regardless of detector outcome (the near-alarm stream).', 'Bench transmitter test (T-R1-3).', 'M'],
        ['D-03', 'Class C sweeps carry the exact start and stop timestamp of the sweep.', 'Protocol review.', 'M'],
        ['D-04', 'Class enable mask, packet head length (32/64) and cadences are CFG items; the LTE fallback profile switches classes C and E off.', 'CFG test.', 'M'],
        ['D-05', 'Raw RSSI and the applied calibration offset are reported separately; no fixed correction (e.g. the handheld\'s +15 dB) is baked into values.', 'Protocol review.', 'M'],
    ]))

    s.append(P('F - Firmware, common', H2))
    s.append(req([
        ['F-01', 'ESP-IDF 5.x, RadioLib for the SX radios, TinyUSB; Arduino component optional.', 'Build review.', 'S'],
        ['F-02', 'Compile-time CONFIG_AERIX_RX_ONLY=y removes TX code paths; radio TX pins and PA control stay in reset state; a unit test greps the linked image for TX entry points.', 'CI test.', 'M'],
        ['F-03', 'HELLO within 2 s of EN release (module type, hw rev, fw version/hash, capability bitmap, PPS present, calibration). Scanning starts after CFG, or after 5 s from NVS defaults if the MAIN S3 is silent.', 'Boot test.', 'M'],
        ['F-04', 'Watchdog on the scan loop; HEALTH every 10 s; no dynamic allocation inside the scan loop.', 'Code review; 1 h soak (T-04).', 'M'],
        ['F-05', 'NVS holds band plan, gates, cadences, module serial, per-band RSSI calibration offsets.', 'CFG persistence test.', 'M'],
        ['F-06', 'OTA through the MAIN S3 (CMD reboot-to-bootloader + UART loader) and through USB.', 'OTA test both paths.', 'S'],
        ['F-07', 'Wi-Fi and BLE on the module ESP32-S3 are disabled.', 'Code review; current measurement.', 'M'],
    ]))

    s.append(P('R1 - Module 1, Sub-GHz SX1276 (860-1020 MHz)', H2))
    s.append(req([
        ['R1-01', 'Radio SX1276 (862-1020 MHz variant; not SX1278, not SX1262). Antenna to RFI_HF via the datasheet HF match; RFO_HF/PA_BOOST unconnected; no RF switch.', 'BOM/schematic review.', 'M'],
        ['R1-02', 'Front-end filter passing 860-1020 MHz (e.g. 5th-order high-pass ~800 MHz + low-pass ~1.1 GHz) to limit GSM-900 downlink overload. The 925-960 MHz band stays inside the sweep plan.', 'T-R1-2 overload test.', 'M'],
        ['R1-03', 'Optional LNA footprint (1 dB NF class) with 0 &Omega; bypass, not fitted in v1.', 'Layout review.', 'C'],
        ['R1-04', 'SPI <= 10 MHz plus RESET, DIO0, DIO1, DIO2 on ISR-capable GPIOs; DIO5 optional.', 'Schematic review.', 'M'],
        ['R1-05', 'Antenna note: 868/915 whips roll off above 930 MHz; a wideband or dedicated antenna is required for 970-1020 MHz coverage.', 'Antenna selection document.', 'S'],
        ['R1-06', 'Default band plan 860-885, 895-928, 970-1020 MHz at 100 kHz (1 080 channels); accepts up to 8 ranges inside 860-1020 MHz.', 'CFG test.', 'M'],
        ['R1-07', 'FSK reception at 57.6, 80.0, 15.235 kbps (defaults) plus 38.4, 76.19, 38.15 kbps; RX BW 200 kHz, AFC on, preamble detector on, sync-word detection off so the first 4 bytes after the preamble are captured as the "word".', 'T-R1-3 word capture.', 'M'],
        ['R1-08', 'LoRa CAD at 500 kHz BW SF6-9 CR 4/7 sync 0x12; also 125/250 kHz SF7-12 sync 0x12 and 0x34 for LoRaWAN/Meshtastic inventory (identify only).', 'T-R1-4.', 'M'],
        ['R1-09', 'Scheduler: RSSI pre-pass (>= 140 µs dwell, ~0.2 s), FSK dwell 50 ms per bitrate only on channels above the gate, LoRa CAD on the same channels, full class C sweep every 5 s. Full cycle <= 60 s quiet, <= 3 min urban.', 'T-R1-5 cycle time.', 'M'],
        ['R1-10', 'Detection: CFG-loadable static word table with normalisation (top bits 00/11 -> mask 0x7FFFFFFF, else strip leading alternating bits); repetition detector (same word, same channel, >= 2 in 20 min -> CANDIDATE); ALARM only for table or repetition hits with RSSI >= gate + 6 dB.', 'Firmware test with recorded words.', 'M'],
        ['R1-11', 'Sensitivity at 868.3 MHz, 38.4 kbps GFSK, 1 % PER: <= -104 dBm at the u.FL.', 'T-R1-1.', 'M'],
        ['R1-12', 'Overload: -20 dBm CW at 942 MHz degrades 868.3 MHz sensitivity by <= 6 dB.', 'T-R1-2.', 'M'],
    ]))

    s.append(P('R2 - Module 2, 2.4 GHz SX1280 (2400-2500 MHz)', H2))
    s.append(req([
        ['R2-01', 'Radio SX1280 or SX1281; RX only; optional 2400-2500 MHz band-pass (<= 1.5 dB IL); no RF switch, or the reference SPDT tied permanently to RX.', 'BOM/schematic review.', 'M'],
        ['R2-02', 'Optional 2.4 GHz LNA footprint with 0 &Omega; bypass, not fitted in v1.', 'Layout review.', 'C'],
        ['R2-03', 'SPI <= 18 MHz plus RESET, BUSY, DIO1 (DIO2 optional).', 'Schematic review.', 'M'],
        ['R2-04', 'Sweep raster A: 2400.0-2499.6 MHz, 400 kHz, 250 channels, 40 µs settle, RSSI in FSK mode; one sweep per second for class C, eight back-to-back every 5 s for scoring.', 'T-R2-1 sweep timing.', 'M'],
        ['R2-05', 'Sweep raster B: 2200.0-2399.6 MHz, 400 kHz, 60 µs settle, every 5 s when enabled. Feasibility below 2400 MHz must be measured; if it fails the capability bit is cleared in HELLO.', 'T-R2-5.', 'S'],
        ['R2-06', 'Fine raster: 256 x 390.625 kHz from 2400 MHz selectable instead of raster A.', 'CFG test.', 'S'],
        ['R2-07', 'LoRa at 2.4 GHz: BW 812.5 kHz, SF5-8, CR 4/6 (SF5) or 4/8, sync 0x14 and 0x12, preamble 12 (ELRS 2.4); 400 kHz steps over a CFG range <= 100 MHz; per-packet RSSI, SNR, frequency error, first 32 bytes.', 'T-R2-4.', 'M'],
        ['R2-08', 'Track mode on CMD: f ± 10 MHz at 400 kHz, 80 µs settle, two passes.', 'CMD test.', 'S'],
        ['R2-09', 'Detection: 16-channel window rule (>= 8 of 16 above gate, broadband guard < 125 of 250), spectral score A (median + 5 dB, width 26-52 bins, persistence >= 3 of 8) and score B (width 18-60 bins, 85 % fill, 5 dB centre-edge margin) as candidate producers; ALARM only after >= 2 consecutive scoring passes above the CFG threshold. Noise histogram in HEALTH only.', 'Firmware test with recorded sweeps.', 'M'],
        ['R2-10', 'Sweep timing: 250 channels in <= 15 ms including settle; RSSI repeatability ±1.5 dB at -60 dBm.', 'T-R2-1.', 'M'],
        ['R2-11', 'RSSI linearity -100 to -30 dBm within ±3 dB at 2440 MHz.', 'T-R2-2.', 'M'],
        ['R2-12', 'PSRAM sized for 8 sweeps x 256 bins plus the 250-bin history.', 'Memory budget review.', 'M'],
    ]))

    s.append(P('R3 - Module 3, 5.8 GHz RX5808 / RTC6715 (5645-5945 MHz)', H2))
    s.append(req([
        ['R3-01', 'Receiver RX5808 (RTC6715) in SPI mode (fixed-channel resistor removed, CH1/CH2/CH3 as SPI CLK/DATA/LE); shielded variant with u.FL preferred, otherwise a short 50 &Omega; trace to a u.FL. Alternatives: any RTC6715/RTC6712 board with SPI synthesizer and RSSI pin.', 'BOM review.', 'M'],
        ['R3-02', 'Tuning range 5645-5945 MHz in ~1 MHz steps (~300 channels); default plan 5725-5899 MHz, 175 channels.', 'T-R3-1.', 'M'],
        ['R3-03', 'RSSI path: analog RSSI -> RC 1 k&Omega; / 10 nF -> ESP32-S3 ADC1; test pad; calibrated attenuation or precision reference; ADC noise <= 1 LSB rms at 12 bits after the filter.', 'T-R3-2.', 'M'],
        ['R3-04', 'Video output not routed; terminated per module datasheet.', 'Schematic review.', 'M'],
        ['R3-05', 'Supply: RX5808 180-200 mA + ESP32-S3 ~60 mA. The designer confirms the base 3V3 rail and ferrite (DC rating >= 500 mA) support 250 mA; otherwise the AUX slot or a lower-current RTC67xx board is used. There is no 5 V on the slot.', 'T-02; ferrite datasheet check.', 'M'],
        ['R3-06', 'Per channel: write synthesizer, wait for lock (measured, default 30 ms), RSSI = mean of 16 ADC samples over 2 ms. Sweep ~5.6 s default, ~10 s extended; class C cadence one sweep per 6 s.', 'T-R3-3.', 'M'],
        ['R3-07', 'Adaptive mode: after a full sweep, re-visit up to 16 channels above the gate every 1 s; full sweep every 6 s. Gate default floor + 10 dB where floor = quietest channel of the first sweep.', 'Firmware test.', 'S'],
        ['R3-08', 'Detection: steep-edge rules (thresholds -65 to -99 dBm in 5 dB steps, gap tolerance 5 channels, width 16-69 MHz, edges stable within 5 MHz, two consecutive sweeps) and the 16-channel window rule as candidate producers; ALARM only after >= 3 sweeps (~18 s) and not on a whitelisted channel; no time-domain classification on this module.', 'Firmware test with recorded sweeps; T-R3-5.', 'M'],
        ['R3-09', 'Class G over USB: continuous RSSI ADC stream on one channel up to 10 kS/s.', 'Host bulk test.', 'C'],
        ['R3-10', 'RSSI curve monotonic -95 to -40 dBm within ±3 dB after two-point calibration stored in NVS and reported in HELLO.', 'T-R3-2.', 'M'],
        ['R3-11', 'LO leakage at the antenna port below -57 dBm.', 'T-R3-6 / T-06.', 'M'],
    ]))

    s.append(P('B - Base-board change (AERIX01 V1 ECO)', H2))
    s.append(req([
        ['B-01', 'Route GNSS TIMEPULSE (MAX-M10S pin 4, series 33 &Omega; R86, today only on the MAIN S3 P3 header) to one currently unconnected header pin of each of the three receiver slots. Proposed: right 1x12 pin 6 (C5 "GPIO15" position); verify the AUX equivalent is free.', 'Netlist review.', 'M'],
        ['B-02', 'Series 33 &Omega; per branch; 3.3 V CMOS, 100 ms high pulse once per second. If any branch exceeds ~15 cm, add one 74LVC1G17 buffer near the GNSS.', 'Layout review; T-05.', 'M'],
        ['B-03', 'No other base-board change; V1 stays as built.', 'ECO review.', 'M'],
        ['B-04', 'MAIN S3 firmware: three UART collectors at 921 600 baud, credits, CFG/TIME distribution (TIME once per second after PPS), UTC conversion of pps_count/t_us, Ethernet forwarding of >= 3 x 3 kB/s, LTE class masking.', 'End-to-end test with three modules.', 'M'],
    ]))

    s.append(P('T - Acceptance tests (first article, before sign-off)', H2))
    s.append(P('Common tests, each module type:', B))
    s.append(tbl([
        ['ID', 'Test', 'Pass criterion'],
        ['T-01', 'Slot fit and bring-up', 'Fits both C5 slots and the AUX slot; RST/BOOT headers work; enumerates on the USB2517 hub; HELLO within 2 s.'],
        ['T-02', '3V3 current during scanning', '<= 250 mA average, <= 500 mA peak (10 ms), including boot.'],
        ['T-03', 'Sensitivity with the scan loop running', 'Within 3 dB of the radio datasheet at the u.FL (proves supply filtering and layout).'],
        ['T-04', 'UART soak', '1 h at 921 600 baud with classes A-F at nominal rate: zero CRC errors, zero credit starvation.'],
        ['T-05', 'PPS timestamping', 'Two modules on one base board timestamp a common test burst within 2 µs.'],
        ['T-06', 'Spurious emission', 'No measurable emission at the antenna port in any band (spectrum analyser, RBW 10 kHz); confirms receive-only in hardware.'],
    ], [16*mm, 50*mm, 104*mm]))
    s.append(Spacer(1, 3))
    s.append(P('Module-specific tests:', B))
    s.append(tbl([
        ['ID', 'Test', 'Pass criterion'],
        ['T-R1-1', 'Sub-GHz sensitivity', '868.3 MHz, 38.4 kbps GFSK, 1 % PER: <= -104 dBm.'],
        ['T-R1-2', 'Sub-GHz overload', '-20 dBm CW at 942 MHz: sensitivity loss <= 6 dB.'],
        ['T-R1-3', 'Word capture', 'Bench generator sending a known 32-bit word at 57.6 kbps: same word in >= 99 % of class B records; frequency error within ±2 kHz.'],
        ['T-R1-4', 'LoRa CAD', 'SF7 / 500 kHz packets at -110 dBm detected on >= 90 % of passes.'],
        ['T-R1-5', 'Cycle time', '<= 60 s with no activity; <= 180 s with 50 active channels.'],
        ['T-R2-1', '2.4 GHz sweep timing', '250 channels in <= 15 ms; RSSI repeatability ±1.5 dB at -60 dBm CW.'],
        ['T-R2-2', '2.4 GHz RSSI linearity', '-100 to -30 dBm within ±3 dB at 2440 MHz.'],
        ['T-R2-3', 'Wi-Fi block behaviour', '20 MHz Wi-Fi at -50 dBm appears as a ~51-bin block and is reported as CANDIDATE, never ALARM, at defaults.'],
        ['T-R2-4', 'ELRS profile', 'SF5 / 812.5 kHz packets at -100 dBm received >= 90 %; frequency error within ±5 kHz.'],
        ['T-R2-5', 'Raster B feasibility', 'RSSI accuracy at 2200-2400 MHz measured and recorded; capability bit set accordingly.'],
        ['T-R2-6', 'No emission', 'T-06 including no CAD-then-TX and no ranging.'],
        ['T-R3-1', '5.8 GHz tuning', 'Every channel of the extended plan locks; lock time <= 35 ms.'],
        ['T-R3-2', '5.8 GHz RSSI curve', 'Monotonic -95 to -40 dBm at 5800 MHz within ±3 dB after calibration.'],
        ['T-R3-3', '5.8 GHz sweep time', '<= 6.5 s default plan, <= 11 s extended plan.'],
        ['T-R3-4', '5.8 GHz current', '<= 250 mA average; inrush <= 500 mA / 10 ms.'],
        ['T-R3-5', '5 GHz Wi-Fi behaviour', '20 MHz Wi-Fi channel at -50 dBm reported as CANDIDATE (steep-edge rule), never ALARM at defaults.'],
        ['T-R3-6', 'LO leakage', 'Below -57 dBm at the antenna port.'],
    ], [16*mm, 44*mm, 110*mm]))

    s.append(P('Appendix - Reference documents', H2))
    s += bullets([
        'docs/hardware/modules/00-common-slot-interface.md - slot interface, UART/USB contract, data classes, base-board ECO, common firmware and tests.',
        'docs/hardware/modules/01-subghz-sx1276-module.md, 02-2g4-sx1280-module.md, 03-5g8-rx5808-module.md - per-module hardware, scan plans, detection rules, tests.',
        'research/briefs/tsukorok-firmware-5.5.12-rf-extraction.md - origin of the default thresholds, word tables and scan plans (all values with firmware addresses).',
        'research/briefs/tsukorok/Tsukorok_5.5.12_detection_methods_summary.pdf and Tsukorok_replication_hardware.pdf - detection-method summary and hardware options.',
        'docs/design/server-baseline-whitelist-plan.md - what the server does with classes B-E (baselines, whitelists, ODID-labelled learning).',
        'PM_AERIX01_V1.PDF - base-board schematic (sheets Dual ESP32-C5, Dual ESP32S3, USB HUB, GNSS).',
    ], S)

    doc.build(s, onFirstPage=footer, onLaterPages=footer)


if __name__ == '__main__':
    build(OUT)
    print('wrote', OUT)
