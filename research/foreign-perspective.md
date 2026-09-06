# Foreign perspective: what the Chinese and Russian/Ukrainian sources add

This document collects everything the research sweep found in Chinese, Russian and Ukrainian
that is **not** already in the English-language material covered by
[landscape.md](landscape.md), [signal-reference.md](signal-reference.md),
[datasets.md](datasets.md) and [hardware-e200.md](hardware-e200.md). It is organised as:

1. [Chinese academic work](#1-chinese-academic-work) - groups, datasets, methods, what is actually novel
2. [Chinese community and vendor knowledge](#2-chinese-community-and-vendor-knowledge) - MicroPhase
   docs and firmware, CSDN/Zhihu/bilibili practice, commercial C-UAS signal-library ideas, accessories
3. [The Russian and Ukrainian detector scene](#3-the-russian-and-ukrainian-detector-scene) - bands,
   methods, hardware, open code, claimed ranges, false-alarm handling
4. [Frontline lessons that change our requirements](#4-frontline-lessons-that-change-our-requirements)
5. [What to take and what to leave](#5-what-to-take-and-what-to-leave)
6. [Gaps](#gaps)

Every title is given in the original language with an English gloss and the URL. Full annotated
entries for all of these are in [sources.md](sources.md); this document only says what they add.

---

## 0. Coverage limits: read this before trusting anything below

The foreign-language material is the weakest part of the evidence base, for mechanical reasons.

| Limit | Detail |
| --- | --- |
| Reachable hosts | In practice only GitHub-hosted material could be fetched or cloned; for every other host the evidence is a search-engine snippet, which [sources.md](sources.md) marks as **snippet** ("only a search-engine snippet was available because the development sandbox cannot reach that host"). Every **verified** foreign entry below is a `github.com` URL. |
| Search budget | Three foreign lenses ran: `web-zh-community` (26 searches, 26 sources), `academic-zh` (26 searches, 25 sources), `web-ru-community` (26 searches, 25 sources) - `finders_all.json`. |
| Verified vs snippet | Chinese community lens: 8 verified / 18 snippet. Chinese academic lens: 8 verified / 17 snippet. Russian lens: 14 verified / 11 snippet. The Russian lens scores better only because one contributor mirrored Telegram channels into a Git repository, which the sandbox could clone. |
| Bibliography share | [sources.md](sources.md) records 296 unique sources: 208 English, **50 Chinese, 24 Russian, 8 Ukrainian**, 6 Dutch. |
| Blocked hosts that matter | `blog.csdn.net`, `zhuanlan.zhihu.com`, `jeit.ac.cn`, `sciengine.com`, `signal.ejournal.org.cn`, `scidb.cn`, `gitcode.csdn.net`, `mbb.eet-china.com`, `habr.com`, `4code.ru`, `smell.co.ua`, `fpvua.org`, `militarnyi.com`, `community.alexgyver.ru`, `cyberleninka.ru`. Everything attributed to those below is snippet-level. |
| Not reached at all | CNKI / 万方 (Chinese theses), Taobao / 闲鱼 listings, Telegram channels in their native form (only a mirror was reachable), the official texts of GB 42590-2023 and GB 46750-2025. |

Two design-critical claims were queued for adversarial verification and lost when the agent budget
ran out. They are labelled **unverified round-1** wherever used here: the E200 O4 DroneID firmware
channel set (`o4-firmware-channels`) and the OcuSync generation PHY summary (`ocusync-phy`).

---

## 1. Chinese academic work

### 1.1 The one group that matters: Zhejiang University

Almost all usable Chinese academic contribution comes from one group at Zhejiang University,
publishing through 电子与信息学报 (*Journal of Electronics and Information Technology*, JEIT).
DroneRFa is by 俞宁宁, 毛盛健, 周成伟, 孙国威, 史治国 and 陈积明 of the Key Laboratory of
Collaborative Sensing and Autonomous Unmanned Systems, with Chengde police
(<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570>); DroneRFb-DIR is by 任俊宇, 俞宁宁,
周成伟, 史治国 and 陈积明 across the ZJU State Key Laboratory of Industrial Control, Hangzhou Dianzi
University and the ZJU Jinhua Institute
(<https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202>). Their contribution is
**data, not algorithms**.

**DroneRFa: 用于侦测低空无人机的大规模无人机射频信号数据集** ("DroneRFa: a large-scale drone RF
signal dataset for detecting low-altitude drones"), JEIT 2024, 46(4):1147-1156,
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570>. The paper PDF was read from the mirror
repository [maojinxiang/DroneRFA_24-Dataset](https://github.com/maojinxiang/DroneRFA_24-Dataset),
so the following is verified rather than snippet-level.

| DroneRFa acquisition parameter | Value |
| --- | --- |
| Receiver | NI USRP-2955, 14-bit ADC, PCIe to a Xeon W-2245 host running LabVIEW |
| Sample rate / instantaneous BW | 100 MS/s I/Q, 80 MHz |
| RX gain | 50 dB, VERT2450 3 dBi omni |
| Channels | RF0 centred 2440 MHz, RF1 centred 5800 MHz (RF0 915 MHz + RF1 2440 MHz for FrSky X20 / Taranis Plus) |
| Distances | Outdoor D00 = 20-40 m, D01 = 40-80 m, D10 = 80-150 m; indoor about 2 m |
| Classes | 24, T0000 (background including Bluetooth and Wi-Fi) through T11000 |
| Segment size / format | >= 100 M samples per segment, `.mat` with keys `RF0_I` / `RF0_Q` |
| Known flaw | capture-store period of 10 M samples, so continuity breaks every 0.1 s |

Source for the whole table: <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570>. The dataset
moved from the JEIT portal to the CAS Science Data Bank,
<https://www.scidb.cn/en/detail?dataSetId=34f0a91e8a544904998b8fdc44477380>
(<https://jeit.ac.cn/web/data/getData?dataType=Dataset1>); the group's release announcement is at
<http://www.isee.zju.edu.cn/2024/0708/c21123a2944315/page.htm>.

**What is genuinely new here is Table 4**, a per-model table of hop-block and video-link statistics
that can be used as hand-written detection rules with no machine learning at all
(<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570>):

| Emitter family | Hop-block bandwidth | Dwell | Other timing |
| --- | --- | --- | --- |
| DJI OcuSync-era (Air 2S, Mini 3 Pro, Mavic 3, M300, M30T) | 2.2 MHz | 0.52 ms | - |
| DJI OcuSync-era (Mavic Pro, Mini 2, P4P RTK, Avata) | 1.1 MHz | 0.52 ms | - |
| DJI Lightbridge-era (P4P, M200, M100, Inspire 2, M600 Pro) | 1.2 MHz | 2.2 ms | 12 ms nearest-hop spacing; 14 ms video period at 68 % duty |
| DJI Avata video | - | - | 10 ms period at 12 % duty |
| FrSky X20 | 0.42 MHz | 2.8 ms | - |
| RadioLink AT9S | 5.0 MHz | 2.1 ms | - |
| Futaba T14SG | 2.0 MHz | 2.0 ms | - |
| 云卓 (Yunzhuo) T12 | 1.7 MHz | 4.6 ms | - |

The Lightbridge row (1.2 MHz / 2.2 ms / 14 ms video frame) is explained by the hardware teardown in
the [dji-firmware-tools wiki P3X OFDM Receiver board
page](https://github.com/o-gs/dji-firmware-tools/wiki/P3X-OFDM-Receiver-board): a WiMAX-derived OFDM
design on an AD9363 (later an Artosyn AR8003) with adaptive BPSK-64QAM over 2.3-2.6 GHz.

The ZJU baseline is also useful as a **window-length budget**: ResNet-18 on a 2 x 1024 x 1024 STFT
(N = 1024, 50 % overlap) of 1 M-sample (10 ms) windows reaches 97.73 % at 53 fps, but the same model
on 256 k-sample (2.5 ms) windows collapses to 72.7 %; reducing frequency resolution to 128 gives
87.9 % at 217 fps (<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570>). At the E200's realistic
host rate that means buffering on the order of 10 ms, i.e. about 200 k samples at 20 MSPS, before
each decision.

**DroneRFb-DIR: 用于非合作无人机个体识别的射频信号数据集** ("RF signal dataset for non-cooperative
drone individual identification"), JEIT 2025, 47(3):573-581, DOI 10.11999/JEIT240804,
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT240804>, data at
<https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202>, PDF at
<https://cdn.sciengine.com/doi/pdf/148A3ABAED5C4D2D97D17B63A9671CF4>. This one targets **individual
airframe fingerprinting**, not model classification: 6 drone types x 3 physical individuals plus one
urban background class, raw I/Q over 2.4-2.48 GHz (80 MHz span), >= 40 segments per class and >= 4 M
samples per segment, containing flight-control (FCS), video (VTS) and ambient interference signals.
All of that is snippet-level; ScienceDB is blocked. It is the only open drone-RF dataset found that
is explicitly built for per-unit identity, which is the harder problem AERIX would eventually face
when correlating an RF track with a Remote ID identity.

### 1.2 Chinese method papers: mostly re-implementations, two useful numbers

| Paper (original title, gloss) | Venue / URL | What it claims | Verdict |
| --- | --- | --- | --- |
| 低信噪比条件下无人机射频信号实时检测方法 ("Real-time drone RF signal detection under low SNR"), 苏志刚/晏翔/韩冰 | 信号处理 2023, 39(5):919-928, <https://signal.ejournal.org.cn/article/doi/10.16798/j.issn.1003-0530.2023.05.016> | 94.63-94.75 % detection over -15 to -6 dB SNR, 97.35-97.50 % over -15 to +15 dB, 1.61 ms inference per spectrogram, multi-branch CNN + attention | Snippet only. The inference budget (1.61 ms) is the interesting part: it is small enough for the Zynq ARM |
| 基于梅尔倒谱系数的无人机探测与识别方法 ("Drone detection and recognition based on MFCC") | JEIT 2025, <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT241111?viewType=HTML> | 98 % accuracy from a **1.6 k-parameter GRU** trained in 9 s on USRP N210 captures; 3-D localisation error below 1 m | Snippet only; authors and affiliation not retrievable. A 1.6 k-parameter model is the smallest credible edge classifier found in any language |
| 基于多维信号特征的无人机探测识别方法 ("Multi-dimensional signal features") | JEIT 2023, <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230302?viewType=HTML> | Adaptive triangular threshold detector, CSI + OMP parameter estimation for location, box-counting dimension and radial-integration bispectrum features, "up to 100 %" | Snippet only; 100 % implies a small test set |
| 基于小波熵特征的无人机射频信号识别算法研究 ("Wavelet-entropy features"), 刘冰/时明心/刘佳琪 | JEIT 2025, 47(8):2736-2745, <https://jeit.ac.cn/cn/article/doi/10.11999/JEIT250051?viewType=HTML> | Wavelet-entropy statistics of hop signals into a DNN | Feature engineering over the same DroneRF-style pipeline |
| 基于噪声指纹的无人机检测与识别 ("Noise-fingerprint detection and identification") | 电子科技大学学报, <https://www.juestc.uestc.edu.cn/article/doi/10.12178/1001-0548.2024309> | Uses the transmitter noise floor as the fingerprint | Only the title was retrievable |
| 基于深度学习的无人机检测和识别研究综述 ("Survey of deep-learning drone detection and recognition") | 信号处理 2024, 40(4), <https://signal.ejournal.org.cn/article/doi/10.16798/j.issn.1003-0530.2024.04.001> | Survey across vision, acoustic, radar and RF | Best Chinese-language literature map. Same issue carries a Transformer + domain-adversarial paper on emitter individual identification (10.16798/j.issn.1003-0530.2024.04.004) |
| Wifi干扰下无人机图传信号的射频识别方法 (patent CN113518374A) | <https://patents.google.com/patent/CN113518374A/zh> | FFT -> EMD denoise -> 30 statistical features -> SVM / decision tree / NN / random forest | The Al-Sa'd / Ezuma DroneRF pipeline re-cast as a patent. A related patent CN118673374A claims a neural-network RF detection method |
| 基于无线电技术的民用无人机侦测与管控方法在监所环境的探究 ("Radio detection and control of civil drones in prisons") | <https://www.hanspub.org/journal/paperinformation?paperid=26813> | Applied deployment view: spectral features, localisation, control | Control is out of scope under [ADR-0001](../docs/decisions/ADR-0001-passive-receive-only.md) |
| 面向远距离高速无人机检测的OFDM通信感知一体化参考信号设计 ("OFDM ISAC reference-signal design for long-range high-speed UAV detection") | 雷达学报 2025, 14(4):842-853, <https://radars.ac.cn/article/doi/10.12000/JR24240> | Active integrated sensing and communication waveform | Recorded only to note that the 雷达学报/通信学报 UAV stream is **active radar**, therefore out of scope for a passive toolkit |

The honest summary, which the Chinese lens itself reached: most Chinese "novel" RF drone classifiers
(EMD plus statistical features plus SVM, wavelet entropy, MFCC, dual-branch SE fusion) are
re-implementations of the Qatar DroneRF / Ezuma pipelines; the genuinely new Chinese contributions
are **the datasets, the hop-feature tables and the GB Remote ID tooling**
(<https://patents.google.com/patent/CN113518374A/zh>,
<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT250051?viewType=HTML>,
<https://github.com/maojinxiang/SE-DCNet>, <https://github.com/luolitao/remoteid>).

### 1.3 Chinese open ML code, and what the verification pass did to it

Three Chinese-authored repositories were cloned and read:

* **[maojinxiang/SE-DCNet](https://github.com/maojinxiang/SE-DCNet)** - "SE-DCNet: 基于双通道融合与
  注意力机制的无人机射频识别" (dual-channel fusion with attention for UAV RF identification), a
  PyTorch project by a student at China University of Petroleum. It fuses a 1-D IQ CNN branch with a
  2-D STFT EfficientNet-B0 branch through a squeeze-and-excitation block, with 1D/2D/ResNet/TCN
  ablations, a noise-robustness sweep at SNR -10, -5, 0, 5, 10 dB (synthetic noise injection) and
  pretrained weights. It reads DroneRFa `.mat` keys `RF0_I` / `RF0_Q` in 1,000,000-sample (10 ms)
  windows, about 650 samples per class, 6:2:2 split, and the test scripts hard-code 9 classes.
* **[maojinxiang/DroneRFA_24-Dataset](https://github.com/maojinxiang/DroneRFA_24-Dataset)** -
  pre-computed 24-class spectrograms, a ResNet-18/CNN demo, and the DroneRFa JEIT PDF. This is the
  practical way to get the DroneRFa paper without SciDB.
* **[FAITHSHUNAA/RF-TCNet](https://github.com/FAITHSHUNAA/RF-TCNet-A-Lightweight-Topology-Compression-Network-for-Drone-RF-Fingerprint-Identification)** -
  a lightweight CNN/transformer hybrid with "dynamic frequency attention", trained on DroneRF and
  DroneRFa spectrograms produced by its own `src/ECSG.py` preprocessing, MIT licence, 8 stars. The
  same author publishes MPAFNet claiming 100 / 99.7 / 99.5 % on three tasks. No paper link.

SE-DCNet is the one that carries evidential weight, because the adversarial pass used it as
third-party evidence against the round-1 "spectrograms clearly beat raw IQ" claim *(verified:
verdict 8, spectrogram vs IQ)*: on DroneRFa with synthetic channels, an **IQ-only CNN-LSTM matches
the STFT-EfficientNet at -10 dB AWGN (about 69 % vs 68 %) while an STFT-ResNet gets 47 % and a plain
IQ-CNN 33 %** - architecture choice matters more than input domain, though STFT models are more
consistently robust under Rayleigh/Rician fading and dual-branch fusion is best
(<https://github.com/maojinxiang/SE-DCNet/blob/main/results/robustness_comparison_three_channels.png>).

The same pass found the counterweight: **SE-DCNet's own evaluation is leaky.**
`prepare_labels.py` shuffles per-offset windows drawn from the same `.mat` files, and all 109 source
files appear in train, validation and test
(<https://github.com/maojinxiang/SE-DCNet/blob/main/prepare_labels.py>,
<https://github.com/maojinxiang/SE-DCNet/blob/main/dataset.py>). Its accuracy numbers are therefore
not comparable to anything evaluated with grouped splits. Use the *relative* ordering of the three
architectures, not the absolute figures. The same warning applies to every Chinese paper in the table
above: none of them documents a session- or unit-level split.

One more structural observation from the Chinese academic lens: **low-SNR results in Chinese papers
come from synthetic noise injection on close-range captures, not from long-range field data**
(<https://www.scidb.cn/en/detail?dataSetId=84cf9101e739402784b1396783881202>,
<https://jeit.ac.cn/web/data/getData?dataType=Dataset1>,
<https://github.com/maojinxiang/SE-DCNet>). DroneRFa's furthest class is D10 = 80-150 m
(<https://jeit.ac.cn/cn/article/doi/10.11999/JEIT230570>).

### 1.4 The DroneID reverse-engineering thread in Chinese

The earliest public Chinese analysis of the DJI broadcast is **独角兽暑期训练营 | 无人机广播信号盲
分析** ("Unicorn Team summer camp: blind analysis of drone broadcast signals"), 2019,
<https://www.anquanke.com/post/id/168279>, from the 360 Unicorn Team. It identified periodic
small-packet broadcasts distinct from the wide video downlink and the uplink control channel and
hypothesised they carried drone identification and location - predating the RUB-SysSec work.

The current thread is a long 2025 CSDN series by **leegang12** under the running heading
"通信算法之NNN" ("Communication algorithms no. NNN"). Only post #292's full title was captured; the
rest are indexed here by the subject the search snippets attribute to them, not by a verbatim title:

| Post | Subject attributed to it | URL |
| --- | --- | --- |
| #254 | O2 video-link PHY | <https://blog.csdn.net/leegang12/article/details/146934408> |
| #256 | Remote ID | <https://blog.csdn.net/leegang12/article/details/146936478> |
| #258 | DJI RID frame format | <https://blog.csdn.net/leegang12/article/details/146977731> |
| #264 | O2 reverse engineering | <https://blog.csdn.net/leegang12/article/details/147245156> |
| #267 | DroneID 640 ms period | <https://blog.csdn.net/leegang12/article/details/147321812> |
| #281 | Open-source DroneID project issues | <https://blog.csdn.net/leegang12/article/details/148402169> |
| #283 | Rate de-matching and Turbo decoding | <https://blog.csdn.net/leegang12/article/details/148471288> |
| #292 | 大疆DJI云哨系统-DroneID物理层协议解析-O1/O2/O3/O4机型都可以CRC正确 ("DJI Yunshao/Aeroscope system - DroneID PHY analysis, CRC correct on O1/O2/O3/O4 models") | <https://blog.csdn.net/leegang12/article/details/149397403> |
| #296 | PHY protocol derived from mass captures | <https://blog.csdn.net/leegang12/article/details/149822783> |
| #305 | Demodulation threshold | <https://blog.csdn.net/leegang12/article/details/149977416> |
| #320 | DroneID packet types | <https://blog.csdn.net/leegang12/article/details/150761143> |

What the snippets contain: DroneID at 30.72 MS/s, 601 occupied subcarriers, 15 kHz spacing, a
Zadoff-Chu sequence in the 4th OFDM symbol, about 10 MHz occupied (15.56 MHz with guards), bursts
roughly every 600-640 ms; OcuSync 2 described as 1024-point FFT OFDM with a cyclic prefix; soft-input
Turbo decoding claimed to be 3 dB better than hard decisions; a demodulation threshold "around 5 dB";
integer and fractional frequency-offset estimation and a rate de-matching module; and four DroneID
packet types (full, serial-only, fully encrypted, key packets)
(<https://blog.csdn.net/leegang12/article/details/149397403>,
<https://blog.csdn.net/leegang12/article/details/148471288>,
<https://blog.csdn.net/leegang12/article/details/149977416>,
<https://blog.csdn.net/leegang12/article/details/147245156>,
<https://blog.csdn.net/leegang12/article/details/150761143>).

**Treat the headline claim as unproven.** The verification pass *(verified: verdict 4, DJI generation
coverage)* concluded that O1/O2/O3 payloads are unencrypted while the **O4 generation (Air 3, August
2023 onward) is encrypted**, that no open repository demonstrates even an O3 decode, and that the
only thing that decodes O4 identity is a licensed cloud service reached through an
`/api/o4online/decrypt?hex=...` call inside MicroPhase's closed firmware binary. leegang12's own
O1/O2/O3-unencrypted vs O4-encrypted statement is consistent with that; the "CRC correct on O1/O2/O3
**and O4**" headline is not, and there is no code to check. The DroneID PHY numbers in the series
match proto17/dji_droneid exactly, so the series is best read as a Chinese-language explanation of
the public decoders plus unverified O2/O4 additions.

The other Chinese DroneID artefact is
**通过USRP B200软件无线电SDR方式解码无人机坐标飞手坐标** ("Decoding drone and pilot coordinates with
a USRP B200"), <https://blog.csdn.net/futon/article/details/131232535> (mirror at
<https://2048.csdn.net/681db80ea5baf817cf4a06d5.html>): a walkthrough claiming real-time decode of
serial number, drone latitude/longitude, home point and pilot coordinates for **Mini 2, Mavic Air 2
and Mavic 2 Pro** on a USRP B200 (AD9364, the same RF family as the E200). The Mini 2 and Mavic Air 2
claims match the open decoders' verified coverage; the **Mavic 2 Pro claim contradicts** the
verification pass, which found DroneSecurity issue #49 (June 2026) reporting "existing decoders don't
support Mavic 2 parameters" *(verified: verdict 4)*. Snippet-only, so it cannot be reconciled here.

`DroneDefence/dji_droneid_antsdr` (<https://github.com/DroneDefence/dji_droneid_antsdr>) surfaces
when searching "ANTSDR DroneID" in Chinese but is only a fork of proto17's work-in-progress MATLAB
and GNU Radio code, with no firmware and no E200/ARM/RX2 references. There is **no separate Chinese
ANTSDR DroneID fork**.

---

## 2. Chinese community and vendor knowledge

### 2.1 MicroPhase's own Chinese documentation is the E200 ground truth

The single highest-value Chinese material in this whole sweep is the vendor's own `source_cn/` tree,
which is more specific than the English pages and was clonable from GitHub, hence **verified**.

| Fact | Value | Source |
| --- | --- | --- |
| RF channel configuration | E200 = "SMA:1T1R IPEX:1T1R" (E310/E316 are "2T2R MIMO" on SMA) | [AntsdrE200_RF_parameters_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_RF_parameters_cn.md) |
| Instantaneous bandwidth | 56 MHz (AD9361) / 20 MHz (AD9363) | same |
| Transmission bandwidth to host | 20 MSPS (E310 only 10 MSPS) | same |
| PS DDR3 | 512 MB on E200 vs 1 GB on E310/E316 | same |
| Clock sync / API | 10M/PPS; libiio and UHD; C/C++/Python | same |
| Box contents | SDR x1, USB cable x1, two rubber-duck antennas, card reader, Ethernet cable, 32 GB SD card | [AntsdrE200_Unpacking_examination_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_Unpacking_examination_cn.md) |
| Factory firmware state | Pluto firmware pre-flashed in QSPI; UHD firmware must boot from SD | same |
| Defaults | IP 192.168.1.10, root / analog, UART 115200 via CH340; BOOT QSPI/SD DIP switch below the Ethernet port | same |
| External reference discipline | IIO device `ad5660mp`: `in_voltage_dac_mode` (0 auto, 1 manual, default 1), `in_voltage_dac_value` (default 23000), `in_voltage_dac_ref_sel` (0 = 10 M, 1 = PPS, 2 = GPS), `in_voltage_dac_locked`; auto-lock takes tens of seconds; needs an SMA-to-MMCX cable | [Antsdr-Clock-calibration_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration_cn.md) |
| UHD identity | `uhd_usrp_probe` reports "[E200] _Product B205MINI(COMPATIBLE)", FPGA version 7.0, "No mboard EEPROM found"; RX antennas TX/RX and RX2; 50-6000 MHz; PGA 0-76 dB in 1 dB steps; BW 200 kHz - 56 MHz; clock and time sources internal/external | [AntsdrE200_UHD_cn.md](https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E200_Reference_Manual/AntsdrE200_UHD_cn.md) |
| Second receiver on Pluto firmware | QSPI: `fw_setenv attr_name compatible; fw_setenv attr_val ad9361; fw_setenv compatible ad9361; fw_setenv mode 2r2t; reboot`; SD: edit `uEnv.txt` `mode=1r1t` -> `2r2t`. **The E200 cannot be flashed over DFU** ("e200 is unsupport") | [antsdr-fw-patch README](https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md) |
| Why the E200 can stream at all | "The ethernet is placed at the PL side" so that baseband above 20 MSPS (about 80 MB/s) does not saturate the Zynq PS; IIO drivers still use the PS GEM controller | [openwifi antsdr_e200 README](https://github.com/open-sdr/openwifi/blob/master/kernel_boot/boards/antsdr_e200/README.md) |
| Vendor throughput test | Two E200s at 7.68 MS/s each gave about 492 Mbit/s aggregate sc16 RX payload | [antsdr_uhd host README](https://raw.githubusercontent.com/MicroPhase/antsdr_uhd/master/host/README.md) |

Two of those rows were corrected by the verification pass and must be quoted in corrected form:

* **Ports.** MicroPhase's "SMA:1T1R IPEX:1T1R" is confirmed, and the board photo shows exactly two
  SMA jacks on the RF edge, but the second pair is **not unreachable**: the Crowd Supply campaign
  states the kit ships with a Hirose U.FL-to-SMA bulkhead pigtail rated under 2 dB loss to 6 GHz
  (snippet-level). There is also **no TX/RX antenna switching on the E200 at all** - the UHD FPGA top
  drives only `tx_amp_en1` *(verified: verdict 1, `rf-ports`;
  <https://www.crowdsupply.com/microphase-technology/antsdr-e200/updates/answering-your-questions>)*.
  See [hardware-e200.md](hardware-e200.md) for the full port map.
* **Host rate.** The Chinese table's flat "20 MSPS" is a vendor figure, not a measurement. The
  corrected statement is that a single 1 GbE port with a 1500-byte MTU caps continuous
  single-channel streaming at about **29.6 MSPS sc16, 39 MSPS sc12, 59 MSPS sc8**, and that the
  achievable rate depends on the firmware personality (IIO/Pluto path fixed at 4 bytes/sample through
  the PS GEM and `iiod` on the ~700 MHz Cortex-A9) *(verified: verdict 2, host streaming tiers)*.

The `ant_impl.cpp` driver source confirms that the IPEX receiver is software-selectable under UHD:
RX antennas are `{"TX/RX", "RX2"}` (lines 968-969), anything else is rejected (line 1378), the
`ant_rx2` flag drives `STATE_RX1_RX2` vs `STATE_RX1_TXRX` (1336-1358) and
`set_active_chains(enb_tx1, enb_tx2, enb_rx1, enb_rx2)` supports two RX chains (1393-1405)
(<https://github.com/MicroPhase/antsdr_uhd/blob/master/host/lib/usrp/ant/ant_impl.cpp>).

### 2.2 The Chinese closed firmware is the only thing that decodes DJI properly

Nothing in `antsdr_doc_en`, `antsdr_uhd` or `antsdr-fw-patch` mentions DroneID. The DroneID
personality is a **binary-only MicroPhase SD image redistributed by a third party**
([alphafox02/antsdr_dji_droneid](https://github.com/alphafox02/antsdr_dji_droneid)); its sources are
not published. Strings pulled from the O4 ramdisk during verification show `sbin/drone_dji_rid_decode`
built "2026/1/14" for "E200", CSV formats `dji_O,2/3,...` and `dji_O,4,...hash`, "O4 packet",
"Enable o4/Disable o4", and the online call `/api/o4online/decrypt?hex=` with
`Authorization` / `auth_secret` / `token_secret` environment variables *(verified: verdict 4, DJI
generation coverage)*. In other words: **the Chinese vendor holds the O4 keys behind a paid cloud
endpoint**, which is the commercial reality that any European toolkit has to plan around. See
[ADR-0006](../docs/decisions/ADR-0006-dji-three-tiers.md).

The channel behaviour of that firmware - that in `device_mode auto` it hops only 2434.5, 5756.5,
5776.5 and 5816.5 MHz, runs 1r1t with a 61.44 MSPS path clock, and that the legacy image uses an FPGA
correlator at `/dev/my-axi-droneid-filter0` - is an **unverified round-1** finding
(`o4-firmware-channels`); the verification budget ran out before it was checked. Do not build a scan
plan on it without re-measuring.

### 2.3 The closest Chinese analogue to what AERIX is building

**[ALPssdz/RF-Vision-UAV-Tracker](https://github.com/ALPssdz/RF-Vision-UAV-Tracker)** (MIT,
"Copyright (c) 2026 Joeylum", 89 commits, 5 stars, Chinese `README_zh.md` and a 473-line Chinese
midterm technical report `docs/rf_midterm_technical_report.md`) is a student project that puts a
**Zynq-7020 + AD9364 node** - the same silicon class as the E200 - behind GbE and runs a three-stage
OcuSync detector on an Orange Pi 5 (RK3588). It was deep-read, so the constants below are verified
from the code.

| Stage | What it does | Key constants |
| --- | --- | --- |
| S1 | Kurtosis-weighted RSSI sector scan | 524,288-sample (13.1 ms) buffers, 3-frame median, `KURTOSIS_BETA=0.40`, `KURTOSIS_REF=3.0`, `KURTOSIS_CAP=20`, EMA alpha 0.35, 50 ms PLL settle, 1 discard read per retune |
| S2 | STFT waterfall + YOLOv8n on the NPU | FFT 2048, hop 1024, Blackman, 640x640 viridis, clip -63..+27 dB, `YOLO_CONF_THRESH=0.30` |
| S3 | CAF-FFT cyclostationary OcuSync-vs-Wi-Fi test | `TAU_OCUSYNC_30K=1333` (40e6/30e3), `TAU_OCUSYNC_15K=2667` (40e6/15e3), `TAU_WIFI=128` (40e6/312.5e3); alpha scan windows 22-30 kHz and 10.5-14.5 kHz; Wi-Fi probe at 250 kHz; thresholds 0.018 / 0.014; PSR 2.2 (3.2 when Wi-Fi is present), CFS 2.0; composite score SDS = 0.45 NCC + 0.25 PSR + 0.20 CFS + 0.10 AFS with detect at SDS >= 1.0 |
| Calibration | Per-sector background NCC floor before every run | 8 buffers per sector, `th = max(hard_floor, (0.4 * p95 + 0.6 * avg) * 2.0)`, written to `s3_thresholds.json` |
| Persistence | Temporal filter over ticks | 3 positive ticks required, 2 at 1.8x threshold, 1 at 3.0x; streak decays 0.5 per negative tick |

Reported field values (all from a **PlutoSDR mock transmitter replaying RFUAV recordings, not a live
drone**): 5785 MHz NCC 3.92 % against threshold 1.80 % with PSR 7.6 and CFS 4.9 confirmed; 5825 MHz
NCC 7.85 % against 3.25 %; a switch-mode power supply burst at alpha 14.4 kHz with NCC 9.40 % but CFS
1.06 rejected; wideband noise at 5745 MHz with PSR 2.35 rejected; a consistent cyclic frequency of
**27.99 kHz** across runs (<https://github.com/ALPssdz/RF-Vision-UAV-Tracker>).

Three things make this the most instructive foreign artefact in the sweep:

1. **It is the only foreign project with a documented false-alarm strategy** - per-sector
   calibration (`rf_zynq/calibrate_s3.py`), a Wi-Fi ambient monitor at the 250 kHz Wi-Fi cyclic
   frequency, a peak-to-sidelobe ratio, a cyclic-frequency-stability test and a temporal persistence
   filter in `system_hub.py`. The RU/UA scene has nothing comparable (section 3)
   (<https://github.com/ALPssdz/RF-Vision-UAV-Tracker>).
2. **Its own report admits what does not work**: stage 2 is not a hard gate, Wi-Fi is expected to
   pass it, the YOLO training set contains no Wi-Fi/4G/5G negatives, and **LTE 15 kHz / 5G NR 30 kHz
   numerologies produce OcuSync-like cyclic peaks in the same alpha windows** - 4G/5G rejection is
   unsolved. Training mAP@0.5 was 0.995 but live confidence only 0.2-0.7, a textbook domain shift
   (`docs/rf_midterm_technical_report.md` sections 0, 4, 6.9, 7.2, 8 and `backend_rk3588/config.py`
   in <https://github.com/ALPssdz/RF-Vision-UAV-Tracker>).
3. **Its 40 MSPS is not sustained streaming.** At int16 I/Q that is 160 MB/s, above GbE, so it
   burst-captures 2,621,440 samples (65.5 ms, 10.5 MB) per tick with gaps and retune sleeps. This
   directly contradicted the round-1 reading and was corrected *(verified: verdict 2, host streaming
   tiers)*: **40 MSPS sc16 is impossible on any 1 GbE firmware**. The burst-with-gaps pattern is
   nonetheless the right pattern for the E200.

The subcarrier-spacing mapping the whole S3 stage rests on (OcuSync 2 = 15 kHz, O3/O4 = about 30 kHz,
Wi-Fi = 312.5 kHz) is the **unverified round-1** `ocusync-phy` finding. Note also that the project's
own README explanation of the measured 27.99 kHz as "CP = 1/4 at 35 kHz spacing" is arithmetically
inconsistent with its own `tau = 1333`. Treat 27.99 kHz as a measured number from a loopback rig, not
as an OcuSync constant.

For contrast, the other Chinese C-UAS repository found,
[pingbiqi/Anti-Drone-System](https://github.com/pingbiqi/Anti-Drone-System-C-UAS-Detection-Jamming-Defense)
("本项目提供专业的无人机反制（C-UAS）技术架构、射频干扰理论及部署方案" - provides C-UAS architecture,
RF jamming theory and deployment schemes), is promotional documentation with no working code, no
AD9361/Zynq/USRP specifics, and an SEO keyword section. It is recorded to document the poor yield of
Chinese open-source direction-finding material.

### 2.4 CSDN, Zhihu and bilibili as practice literature

| Original title (gloss) | URL | What it adds |
| --- | --- | --- |
| 无人机侦测：频谱无线电侦测设备技术详解 ("Drone detection: technical details of spectrum radio detection equipment") | <https://blog.csdn.net/dong2010hong/article/details/142590321> (+ [138107124](https://blog.csdn.net/dong2010hong/article/details/138107124), [142896540](https://blog.csdn.net/dong2010hong/article/details/142896540)) | The best available checklist for a **signal-library schema**: 300-6000 MHz monitored range, sensitivity quoted at -120 dBm or better, FFT feature extraction matched against a make/model signature library, amplitude-comparison direction finding, multi-station TDOA and AOA, black/white lists, pilot (飞手) localisation, 24/7 360-degree operation |
| 无人机跳频信号识别技术介绍 ("Drone frequency-hopping signal recognition") | <https://www.techphant.cn/blog/103897.html> | Vendor account of FHSS control-link detection: wideband scan, FFT plus energy detection for hop transients, extraction of carrier, dwell time and hop sequence, then HMM or deep-learning pattern engines; claims >95 % recognition of random hop sequences; quotes RC transmitters cycling their hop set about every 7 ms |
| 软件无线电SDR加人工智能算法实现无人机频谱探测 ("SDR plus AI for drone spectrum detection") | <https://blog.csdn.net/yuejich/article/details/136309170> | Cyclostationary features and pseudo-Doppler DF on USRP prototypes; micro-Doppler for "silent" drones; VITA 49 spectrum-monitoring platforms with fingerprint libraries and TDOA |
| 大疆无人机SDR 链路 ("DJI drone SDR link") | <https://blog.csdn.net/dota51888/article/details/147770477> | DJI links auto-switch among 2.4 GHz, 5.8 GHz and the DFS (5.2 GHz) band based on measured interference - the justification for scanning all three |
| 大疆图传技术参数对比 ("DJI video-link parameter comparison") | <https://blog.csdn.net/qq_43464910/article/details/151153810> | Lightbridge described as FPGA + AD9361 (per <https://www.besovideo.com/detail?t=2&i=1605>); OcuSync as dual-band 2.4/5.8 with real-time spectrum analysis, OFDM, MIMO, H.265, FEC, AMC, hopping, power control; M300 RTK range up to 15 km (FCC) |
| DJI FPV图传系统全面解析：Wi-Fi、LightBridge、OcuSync | <https://zhuanlan.zhihu.com/p/114100500> | OcuSync first shipped on the Mavic Pro as a Lightbridge upgrade; bidirectional sensing avoids interfered channels and adapts bitrate, saving about 30 % bandwidth |
| DJI大疆OcuSync系列通信协议终极指南：O1/O2/O3/O4 | <https://zhuanlan.zhihu.com/p/667452286> | Model-to-generation glossary; CP-OFDM plus hopping for control; O3 adds triple adaptation (frequency/bit rate/protocol), OFDM-MIMO and LDPC |
| 大疆OcuSync图传技术解析 | <https://blog.csdn.net/weixin_29216049/article/details/158087603> | Claims "a single video transmission module occupies 8 MHz bandwidth" - **contested**, conflicts with the DJI SDK 10/20 MHz settings and tmbinc's ~18 MHz measured occupied bandwidth; recorded as a contradiction, not a fact |
| 反无人机系统算法分析、计算设备硬件配置推荐 ("C-UAS algorithm analysis and compute recommendations") | <https://zhuanlan.zhihu.com/p/32801277889> | How Chinese integrators partition the problem: RF + radar + EO fusion, Doppler and TOA positioning before directed jamming |
| 侦测与反制 - 无人机防御 (Hikvision C-UAS product page) | <https://www.hikvision.com/cn/products/drone-products/udf/detection-prevention/> | Mainstream vendor taxonomy: spectrum + EO + radar detection -> alert -> force return-to-home or landing. A list of 50+ Chinese C-UAS suppliers for spec-sheet mining is at <https://www.aibangfly.com/a/6327> |
| 大疆发布 DJI O4 地面站 ("DJI releases the O4 ground station") | <https://www.ithome.com/0/965/621.htm>, <https://digi.ithome.com/archiver/823/622.htm> | O4 Air Unit / Air Unit Pro operate in **5.170-5.250 GHz and 5.725-5.850 GHz**; the O4 ground station switches automatically among sub-2 GHz, 2.4 GHz, 5.2 GHz and 5.8 GHz with a 12-antenna dual-polarised array; latency 20 ms standard, 15 ms racing |
| 基于AD9361的图传hdzero图传介绍 ("Introduction to the AD9361-based HDZero video link") | <https://www.kechuang.org/t/89181> | HDZero architecture: a Divimath (迪威码, Xi'an) DM5680 baseband OFDM-modulates uncompressed video and hands I/Q to an AD9361; RX demodulates OFDM from an AD9361; latency under 1 ms, up to 1080p30; range 1.3 km at 5.8 GHz / 20 dBm and 22 km at 520 MHz / 30 dBm (<https://news.eeworld.com.cn/mp/ADI/a60568.jspx>) |
| ELRS技术详解：基于LORA的低功耗远程无线电系统及其特性 | <https://blog.csdn.net/csdnpmsm/article/details/137477858> (+ <https://zhuanlan.zhihu.com/p/720873035>, <https://zhuanlan.zhihu.com/p/695156875>, <https://blog.csdn.net/lida2003/article/details/143709303>) | Chinese labels for the ELRS parameter set: SX127x at 433/868/915 MHz, SX1280/1281 at 2.4 GHz, LoRa and FLRC, adaptive FHSS, in-band time-division telemetry, power steps 25/100/250/500/1000/2000 mW (14-33 dBm). Nothing beyond the English ELRS docs, and the decodability question is settled elsewhere *(verified: verdict 3, ELRS decodability: every 2.4 GHz ELRS mode is detect/classify-only today)* |
| 无人机测试系列：大疆精灵3遥控+图传信号实测 ("Measured Phantom 3 RC and video signals") | <https://mbb.eet-china.com/blog/1675150-368785.html> | A 2016 spectrum-analyser bench measurement of a Lightbridge-era uplink and downlink. Page blocked; only its existence is established |
| 我国无人机，FPV图传与遥控链路通信频段划分 ("China's frequency allocation for UAV FPV video and RC links") | <http://www.idc-rf.com/news/1183.html> (+ <https://www.techphant.cn/blog/98863.html>) | Claims to describe the MIIT allocation for UAV links (sub-GHz, 1.4 GHz, 2.4 GHz, 5.8 GHz). **The actual numbers were not in the snippet.** Chinese industrial drones may use allocations that a EU-centric scan misses; must be verified by hand |
| 教程分享 \| C-RID 无人机唯一产品识别码广播模块使用教程 (bilibili) | <https://www.bilibili.com/video/BV1RRtEzvEZS/> | A Chinese add-on module that broadcasts the GB 42590 唯一产品识别码 (unique product identification code) - a cheap known-good transmitter for bench-testing a receiver against Chinese-format Remote ID |
| 无人机射频侦测开源数据集汇总 ("Roundup of open drone RF detection datasets") | <https://gitcode.csdn.net/6a2459d5662f9a54cb7ac49a.html> | A continuously updated Chinese list of open drone-RF datasets. Blocked; worth pulling by hand to cross-check [datasets.md](datasets.md) |

The HDZero project's own documentation repository also carries Chinese and Russian translations that
are fetchable from GitHub: `docs/zh/box-operation.md` gives the low band table L1..L8 = 5362, 5399,
5436, 5473, 5510, 5547, 5584, 5621 MHz, and `docs/zh/camera-nano90.md` explains that 540p60
"通过降低 HDZero 视频带宽" (lowers HDZero video bandwidth) for penetration and range
(<https://github.com/hd-zero/hdzero-docs>).

### 2.5 Chinese Remote ID tooling (the surprise find)

One Chinese developer, `luolitao`, has published the only open implementations of China's broadcast
Remote ID formats. These matter to AERIX because an Open Drone ID parser silently drops the newer
Chinese frames. The regulatory framing is in [regulatory.md](regulatory.md); what belongs here is the
tooling and the byte-level discrimination rules, all **verified from cloned code**:

* **[luolitao/remoteid](https://github.com/luolitao/remoteid)** - "Remote ID Monitor -
  无人机远程识别监控系统", Go 1.25 + gopacket/libpcap on a Raspberry Pi in Wi-Fi monitor mode, Vue 3
  front end, SQLite, WebSocket, TUI, offline pcap parsing, CSV/JSON export, MIT licence. It decodes
  **three** protocols: ASTM/ASD-STAN, GB 42590-2023 and GB 46750. All three share vendor IE OUI
  `FA:0B:BC` with OUI type `0x0D` (`backend/internal/drone/parser.go`); the legacy OUI `06:05:04` /
  type `0xFD` is also accepted. Discrimination (`cmd/ridparse/main.go`): GB 46750 if `data[1] == 0xFF`
  and the version high 3 bits are `0x1`; otherwise the message header low nibble `0x1` = GB 42590 and
  `0x2` = ASTM F3411-22a. Wi-Fi Beacon and NAN action frames (subtype 13, WFA OUI `50:6F:9A` +
  `FA:0B:BC`), 2.4 GHz only, no BLE.
* **[luolitao/esp32-crid](https://github.com/luolitao/esp32-crid)** - ESP32-S3 scanner and simulator
  built on the official `opendroneid` library, emitting single-line JSON
  (`uav_discovery` / `uav_update` / `uav_timeout`) with mac, rssi, channel, transport, protocol,
  basic_id, location, self_id and a 5-minute timeout tracker. Header discrimination: ASTM `0xF1` with
  a 2-byte pack header, GB 42590 `0xF1` with a 3-byte `[0xF1][25][MsgCount]` header, GB 46750 `0xFF`.
* **[luolitao/XC-RemoteID](https://github.com/luolitao/XC-RemoteID)** - the only open GB 46750-2025
  transmitter: ESP32-C3/S3 firmware modelled on ArduRemoteID, BLE 5 extended advertising (service
  data AD type `0x16`, UUID `0xFFFA`, subtype `0x0D`, advertising interval 1600 = 1 s, +9 dBm) plus
  Wi-Fi beacon vendor IE, MAVLink input, a 120 h rolling flight log and a take-off interlock. Packet
  format: type + version + length + a bitmap of 21 data items; identity is the unique product code
  (GB/T 41300) plus a real-name registration flag; coordinates WGS-84 or CGCS2000.
* **[luolitao/esp32-crid-sim](https://github.com/luolitao/esp32-crid-sim)** - MIT beacon emulator
  with a web UI, OTA and patrol-track simulation; contains a complete GB 46750 encoder
  (`rid_gb46750.c`, byte 0 = `0xFF`, byte 1 = version `0x20`, bytes 2-4 flag bitmap, then fields in
  flag order) and the five fixed 25-byte GB 42590 messages (Basic ID `0x0`, Location `0x1`, Self-ID
  `0x3`, System `0x4`, Operator ID `0x5`; no Auth message is required by the Chinese standard).

Two consequences for the toolkit. First, **GB 42590 additionally permits Wi-Fi broadcast at
5725-5829 MHz** (<https://blog.csdn.net/qq_41126242/article/details/143920008>), a band none of the
open Chinese receivers monitors because they are all 2.4 GHz Wi-Fi chips - but which an E200 covers
natively. Second, **the two open GB 46750 implementations disagree on the timestamp encoding**:
XC-RemoteID's README says 6-byte Unix milliseconds, while the esp32-crid-sim encoder writes a 4-byte
count of seconds since 2019-01-01. The standard was published 2025-10-31 and takes effect
2026-05-01, with a 12-month retrofit window and a 36-month transition, network reporting mandatory
and ADS-B explicitly forbidden (<https://github.com/luolitao/XC-RemoteID>); its official text at
<https://www.caac.gov.cn/XXGK/XXGK/BZGF/BZGF_GJBZ/202601/t20260120_229783.html> must settle the
timestamp question before anyone writes a decoder.

### 2.6 Accessories and sourcing

Thin, and honestly so. The official MicroPhase Taobao listing for the E200 is item id
`691394502321`, linked from the firmware repository (E310 = `647986963313`, E310V2 =
`708976727818`) (<https://github.com/MicroPhase/antsdr-fw-patch/blob/master/README.md>). **No Taobao
or 闲鱼 price, no GPSDO SKU, no IPEX-to-SMA pigtail SKU and no 10M/PPS MMCX cable SKU surfaced in any
search**; the AD9363 variant appears on AliExpress at about US$364
(<https://www.crowdsupply.com/microphase-technology/antsdr-e200/updates/answering-your-questions>).
The clock-calibration page shows the 10M/PPS hookup on an E310 photo and states the E200 method is
identical, so an SMA-to-MMCX cable is needed and is not in the box
(<https://github.com/MicroPhase/antsdr_doc_en/blob/master/source_cn/device_and_usage_manual/ANTSDR_E_Series_Module/ANTSDR_E310_Reference_Manual/Antsdr-Clock-calibration_cn.md>).

---

## 3. The Russian and Ukrainian detector scene

### 3.1 What actually exists as open code

The RU/UA open-source scene is **ESP32 and RSSI hardware, not SDR**. Four repositories carry the
whole field:

| Project | What it is | Licence / status |
| --- | --- | --- |
| [bobberdolle1/SkySweep32](https://github.com/bobberdolle1/SkySweep32) - "SkySweep32 - Мультидиапазонный детектор БПЛА" (multi-band UAV detector) | ESP32-S3 with CC1101 (855-925 MHz, sampled at 860/890/920 MHz), SX1281 (2.4 GHz instantaneous RSSI) and RX5808 (eight hardware-selected 5.8 GHz channels with analog RSSI), plus GNSS, microSD, ESP-NOW mesh and a BLE Remote ID parser (service UUID `0000fffa`, ASTM F3411-22a Basic ID / Location / System / Operator ID) | GPL-3.0, last commit 2026-08-13, README status "NOT PRODUCTION VALIDATED"; Rev C hardware has never been built or RF-characterised |
| [Stanislav-sipiko/passive-sdr-radar](https://github.com/Stanislav-sipiko/passive-sdr-radar) - "Система пассивного радиолокационного наблюдения на основе KrakenSDR" | Passive coherent location using DVB-T2 at 546 MHz as illuminator, KrakenSDR 5-channel + Raspberry Pi 5, GPS/PPS sync; pipeline `capture/kraken_reader.py` -> `caf/caf.py` -> `detect/cfar.py` -> morphology and DBSCAN clustering -> `track/tracker.py` (Kalman + Hungarian) -> `realtime/ws_server.py`, about 2.2 k lines of Python | GPL-3.0, last commit 2025-10-12. **Its own TODO says real KrakenSDR data is not yet connected** |
| [edwardrybka/FPV_DETECTED_1.2_5.8GHZ](https://github.com/edwardrybka/FPV_DETECTED_1.2_5.8GHZ) | Ukrainian open-hardware analog FPV detector: Raspberry Pi Pico plus RX5808 modules and a TA8804 video demodulator at 1.2 and 5.8 GHz. Claimed range about 1.6 km in open field for a 200 mW transmitter at 1.8 m height | Apache-2.0, 18 commits, README in Ukrainian |
| [p3gass/Drone-Finder-ELRS](https://github.com/p3gass/Drone-Finder-ELRS) | EdgeTX Lua script turning a RadioMaster TX15 into a Geiger-style RSSI/LQ finder for a lost ELRS aircraft, surfaced through a Ukrainian forum thread "Lua скрипт для пошуку дрона за RSSI" | GPL-3.0. Marginal, but it shows the scene reads RSSI/LQ from the ELRS link itself |

The single richest Russian-language artefact is not code at all:
**[techuav/techuav.github.io](https://github.com/techuav/techuav.github.io)**, a static mirror of the
Telegram channels "ТЭЧ БпЛА | FPV", "ПЛАТФОРМА_FPV" and "БПЛА ВСУ" - 11,470 HTML pages, last commit
2025-08-07, clonable and greppable offline. It contains firmware manuals (MilELRS, MILPACK, TBF,
G13), VTX channel tables, detector comparisons, translated Ukrainian ("Борьба с БПЛА", ВСУ 2019) and
US ("ATP 3-01.81 Counter-UAS", 2023) manuals, the Ukrainian 2024 unmanned-systems doctrine, and
threads on fibre-optic FPV drones that emit no RF at all. Everything in section 4 below with a
`techuav.github.io` URL was read from that clone, so it is **verified as text** - though the text is
frontline chat and vendor marketing, and its claims about ranges and detector performance are not
independently measured.

### 3.2 Detection method: RSSI tiers, video demodulation, and manual waterfalls

There is no open RU/UA IQ-level classifier. The methods actually used are:

* **Normalised RSSI tiering.** SkySweep32 computes a relative normalised RSSI 0-100 and fires
  LOW / MEDIUM / HIGH / CRITICAL at 45 / 60 / 75 / 85 (`src/config.h`). Its README explicitly states
  that it does **not** identify transmitters, does not direction-find, does not jam and does not deny
  GPS - earlier revisions advertised "fingerprinting" and "countermeasures" that the current code
  does not contain (<https://github.com/bobberdolle1/SkySweep32>).
* **Analog video demodulation as the detector.** The Ukrainian "Чуйка 3.0" (Chuyka 3.0) works by
  demodulating analog video so the operator literally sees the enemy pilot's picture; it scans
  900-1680, 3060-3700 and 4990-6000 MHz with parallel fast auto-scan, claims 4 km, shows up to three
  sources with their frequencies, and raises an audio alert as the drone approaches
  ([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Украинские_каналы_сообщают_о_создании_детектор_видеосигнала_Чуйка_3.0_для_защиты_от_дронов_ВС_РФ..html)).
  The same three-receiver-module architecture (1.2 / 3.3 / 5.8 GHz, microcontroller-scanned) is what
  the Ukrainian market sells as SENSE-3 / HUNTER-3 / "Чатовий"
  (<https://www.martial.com.ua/shop/portatyvni-detektory-droniv/detektor-droniv-sense-3-trydiapazonnyj-videoskaner-fpv-droniv-1-2-3-3-5-8-hhts/>)
  and what the 2025 Мілітарний buyer's guide describes, adding that "FPV most often works in 1.2, 2.4,
  3.3 and 5.8 GHz" and listing "Xenon-L" covering 0.9, 1.2, 2.4 and 4.9-6.0 GHz
  (<https://militarnyi.com/uk/special-projects/yak-vybraty-detektor-droniv-oglyad-modelej-i-klyuchovi-kryteriyi-vyboru/>).
  SKYNOVA's "Перець" covers 915 MHz, 2.4 GHz and 5.8 GHz
  (<https://www.martial.com.ua/shop/portatyvni-detektory-droniv/detektor-droniv-sense-3-trydiapazonnyj-videoskaner-fpv-droniv-1-2-3-3-5-8-hhts/>,
  <https://militarnyi.com/uk/special-projects/yak-vybraty-detektor-droniv-oglyad-modelej-i-klyuchovi-kryteriyi-vyboru/>).
* **Manual spectrum reading.** A Ukrainian field instruction from Kyiv, 2024 ("Instructions for
  anti-UAV crew: drone detector based on tinySA Ultra spectrum analyzer") uses a tinySA Ultra on
  firmware v3.2.0 with multi-band view, highlighting of drone-like signals and an alarm
  (<https://rtotech.org/wp-content/uploads/2025/01/Tiny_SA_drone.pdf>; tinySA firmware source at
  <https://github.com/erikkaashoek/tinySA>). The Russian comparison
  "Анализатор спектра или детектор дронов: что выбрать" concludes that SDR analysers such as HackRF
  show digital signal structure better while sweep analysers (tinySA ZS407) measure the level and
  frequency of analog carriers more accurately, and that signature detectors passively look for
  OcuSync, Autel, ELRS, Crossfire and Wi-Fi link signatures
  (<https://fpv-club.ru/analizator-spektra-ili-detektor-dronov-otlichija/>).
* **DIY 2.4 GHz sniffers.** The AlexGyver community threads
  "Сигнализатор приближающегося квадрокоптера" and "Методы обнаружения сигналов управления БПЛА"
  recur with RX5808 + Arduino 5.8 GHz detectors, nRF24L01-based 2.4 GHz sniffers and ESP32-S2
  controllers, and discussion of reading control links off SDR waterfalls, with no code released
  (<https://community.alexgyver.ru/threads/signalizator-priblizhajuschegosja-kvadrokoptera.7280/>,
  <https://community.alexgyver.ru/threads/metody-obnaruzhenija-signalov-upravlenija-bpla-opredelenie-ix-parametrov.8000/>).

### 3.3 Bands the commercial RU/UA detectors watch, and what they claim

| Device (original name) | Coverage | Claimed performance / price | Source |
| --- | --- | --- | --- |
| Чуйка 3.0 (UA, video detector) | 900-1680, 3060-3700, 4990-6000 MHz | 4 km; up to three simultaneous sources; shows the pilot's picture | [techuav mirror](https://github.com/techuav/techuav.github.io) |
| SENSE-3 / HUNTER-3 / Чатовий (UA) | 1.2 / 3.3 / 5.8 GHz simultaneously | picture output; three receiver modules | <https://www.martial.com.ua/shop/portatyvni-detektory-droniv/detektor-droniv-sense-3-trydiapazonnyj-videoskaner-fpv-droniv-1-2-3-3-5-8-hhts/> |
| Xenon-L (UA) | 0.9, 1.2, 2.4, 4.9-6.0 GHz | - | <https://militarnyi.com/uk/special-projects/yak-vybraty-detektor-droniv-oglyad-modelej-i-klyuchovi-kryteriyi-vyboru/> |
| Arrakis 4 (UA) | FSK at 860-928 and 955-1020 MHz; ELRS/FPV at 720-915 MHz | 3-4 km | same |
| unnamed multi-band (UA) | 433/450/750/868/915/921 MHz plus SDR 2.4 GHz with ELRS (LoRa) scanning | 500-2000 m | same |
| Булат v3 / v4 (RU) | handheld omnidirectional | up to 1.5 km, up to 15 h autonomy; in a field test against 5.8 GHz video + 915 MHz ELRS **the 5.8 GHz response was delayed** | <https://4vision.ru/blog/portativnyj-vsenapravlennyj-detektor-dronov-bulat-v3-obzor-modeli>, <https://uralsistems.ru/blog/bulat-v4-obzor-tehnicheskih-harakteristik-i-vozmozhnostej>, <https://static.insales-cdn.com/files/1/2222/36325550/original/detektor-bpla-bulat-v4_quickguide_main.pdf> |
| Сокол-10 / Skydroid S-10 (RU) | 300 MHz - 6 GHz | - | <https://4vision.ru/blog/portativnyj-vsenapravlennyj-detektor-dronov-bulat-v3-obzor-modeli> |
| Мастерок-4 (OKB «Чистое небо», RU) | 300 MHz - 7.2 GHz | spectrum analyser with DF, networking, laptop mode | [techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/РЭР_и_подразделениям_про_борьбе_с_дронами_-_изделие_спектроанализатор_радиодиапазона_Мастерок-4_от_О.html) |
| «Тень» (RU) | 100 MHz - 10 GHz | promises DF, networked operation, laptop front-end | same |
| Дроноскоп 4.7 (RU) | to 7.3 GHz | one of only two things named as able to see FPV video above 6.2 GHz (the other is an Arinst SSA R3) | [techuav mirror](https://github.com/techuav/techuav.github.io) |
| Alissum / Алиссум (КВАДРО КОД, RU) | 4800-6200 MHz | full sweep with signal analysis in 3-5 s; vendor claims neural-network recognition of UAV signal types that rejects Wi-Fi; Alissum-6 19,000 RUB, about 1 km line of sight, under 90 g; Alissum-8 62,000 RUB; **over 130 FPV channels in the 5.8 GHz band as of early 2025** | <https://4code.ru/publications/band5800> |
| СОВА 3.3/5.8 (Гагаринг, RU) | two receivers, 3.3-3.6 GHz and 4.9-6.1 GHz | head up to 300 m from the operator over twisted pair; marketed both as FPV receiver and as a drone detector / video interceptor; 40,000 RUB | [techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Выносной_видеоприемник_СОВА_3.3_5.8.html) |

Two things follow for a sweep scheduler. Field reports of **delayed reaction to 5.8 GHz analog video
and ranges of about 1-1.5 km** mean the video band needs sub-second revisit
(<https://4vision.ru/blog/portativnyj-vsenapravlennyj-detektor-dronov-bulat-v3-obzor-modeli>,
<https://4code.ru/publications/band5800>). And the "more than 130 FPV channels in 5.8 GHz" figure
means a channel-by-channel receiver has a bad revisit problem that a 56 MHz-wide SDR does not.

### 3.4 False-alarm handling: essentially absent in the open scene

SkySweep32 has fixed RSSI tiers and no signal identification at all. The neural-network signal
classification advertised by Russian vendors (Alissum's Wi-Fi rejection, Дроноскоп) is closed
(<https://github.com/bobberdolle1/SkySweep32>, <https://4code.ru/publications/band5800>). The
companion publication "МАТРАСЕР" describes a tool for recording the radio air with the detector,
i.e. the vendor's own training-data collection loop
(<https://4code.ru/publications/matracer>) - the pattern AERIX would need for its own captures, but
the tool itself is closed. The only documented false-alarm machinery in any foreign source is the
Chinese RF-Vision project's calibration / PSR / CFS / AFS / persistence stack (section 2.3).

### 3.5 Russian academic and press material adds nothing operational

* CyberLeninka: "Макет пеленгатора на основе SDR-технологии" (SDR direction-finder prototype,
  <https://cyberleninka.ru/article/n/maket-pelengatora-na-osnove-sdr-tehnologii>) and
  "Обнаружение беспилотных летательных аппаратов: существующие решения и возможности" (survey of
  radar, radio, electro-optical and acoustic detection,
  <https://cyberleninka.ru/article/n/obnaruzhenie-bespilotnyh-letatelnyh-apparatov-suschestvuyuschie-resheniya-i-vozmozhnosti>).
  Abstracts only; no code, no drone RF data. A third paper on neural reconstruction of UAV radio
  signals trains a variational autoencoder on RadioML 2018.01A, not on drone data.
* Habr and the Russian security press re-report the German DroneID work rather than producing tooling:
  <https://habr.com/ru/news/720088/> (March 2023, "researchers intercept DJI drone signals and obtain
  pilot location"), <https://habr.com/ru/articles/657997/> (Aeroscope receiving DroneID up to about
  30 miles), <https://xakep.ru/2023/03/03/droneid-hacked/>,
  <https://www.securitylab.ru/news/536745.php>. **No Russian or Ukrainian open-source DroneID decoder
  was found.**
* The one Russian open-source idea worth keeping is the passive-radar structure and its Habr
  write-up "Как мы превратили цифровое ТВ в радар" ("How we turned digital TV into a radar",
  <https://habr.com/ru/articles/966044/>): DVB-T2 at 546 MHz as a stable, powerful, known-structure
  OFDM illuminator, with KrakenSDR and a Raspberry Pi 5 costing about as much as a router, deployable
  from a balcony. For AERIX this is the only credible published route to detecting **RF-silent
  fibre-optic FPV drones**, which the techuav mirror discusses at length. Localisation is deferred in
  [ADR-0009](../docs/decisions/ADR-0009-localisation-deferred.md); this is a note for later.
* Russian Remote ID is **network-based and not locally receivable**: Government Decree No. 83 of
  2 February 2026 makes connection to ЭРА-ГЛОНАСС (ERA-GLONASS) mandatory from 1 March 2026 for civil
  UAVs over 250 g, transmitting an identification index, category, altitude and coordinates to the
  system operator (<https://www.interfax.ru/russia/1071959>). ComNews adds that AO GLONASS is testing
  a hybrid "Russian DroneID analogue" for areas without cellular coverage and that ERA-GLONASS ingests
  cellular, satellite, hybrid trackers and ADS-B (<https://comnews.ru/content/244060>). No Bluetooth
  or Wi-Fi broadcast standard was found, so there is nothing for an SDR to receive.

---

## 4. Frontline lessons that change our requirements

This is the part of the foreign material with the highest impact on the toolkit, and it comes almost
entirely from the techuav mirror, read as text from the clone.

### 4.1 Frequency-agile ELRS forks

**Прошивка MILELRS v3.50 Руководство пользователя** ("MilELRS v3.50 firmware user manual"), the
Russian mirror of the Ukrainian military ExpressLRS fork (based on ELRS 3.5.2), is the single most
concrete description of what a frontline RC link looks like in RF terms
([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ПЛАТФОРМА_FPV/Прошивка/Прошивка_MILERLS_оппонентов.html)).
The relevant text reads: "Прошивка поддерживает три типа радиочипов: SX1276/78 - диапазоны «433»,
«900», частоты 360-560, 720-1020; SX1280 - полоса «2400», частоты 2100-2700; LR1121 - частоты
150-2800, разделенные на несколько диапазонов".

| Radio chip | Nominal ELRS bands | Frequencies actually driven |
| --- | --- | --- |
| SX1276/78 | "433", "900" | **360-560 MHz and 720-1020 MHz** (some modules do not work below 740 MHz) |
| SX1280 | "2400" | **2100-2700 MHz** |
| LR1121 | "433", "900", "2400" | **150-2800 MHz**, with low output power in 1010-2100 MHz |

Other manual features that matter to a detector:

* `CUSTOM_FREQ=740,760,0` sets an arbitrary operating band (here 740-760 MHz, a 20 MHz span). The
  third parameter is a **separate telemetry frequency, whose stated purpose is to hide the main
  control frequency from the enemy**; `CUSTOM_FREQ2` adds a second band (for example 940-960) and
  telemetry bandwidth is half the main band.
* `EW_SCANNER='12,730,830'` sweeps 730-830 MHz from a remote switch, `EW_RSSI` shows the maximum
  jammer level, and it works best on a True Diversity receiver with two radio modules (for example a
  Happymodel ES900 Dual). "Пеленгация РЭБ" (v2.52) uses those two antennas to determine the direction
  to a jammer, and a `DETECTOR` mode (v3.40) turns a receiver module into an analyser and direction
  finder for other signals.
* `MULTI_BAND` (v2.20) duplicates the link over several parallel ExpressLRS pairs; a Gemini TX
  auto-switches between bands (v3.20). Packet rates 14 / 25 / 44 / 82 Hz; the 2.4 GHz 22 Hz and 44 Hz
  modes add 6 dB and 3 dB of sensitivity.
* Encryption uses `RX_KEY` / `TX_KEY` generated on `milpilots.com`, and `TX_LOCK` prevents copying
  the firmware. The manual states the functionality was co-developed with the "Барвинок-5" team.
* Named hardware in the 433 band: ELRS400UA (390-500 MHz), ChDB Mk3 (410-525), LOKI_400 (365-535,
  1 W), COALAS_45 (410-530, 7 W). LR1121 hardware: BVNA / Ariadna T1A0/R1A0 (1850-2050 MHz),
  AERONETIX LR1121 (150-700 MHz), CYCLONE LR1211_400 (370-590).

Барвінок-5, the Ukrainian sibling, **disables telemetry entirely** because "telemetry unmasks the
control channel", offers a two-channel mode with two transmitters and receivers on different
frequencies, and ships a backpack firmware with extended video channel sets
(<https://fpvua.org/resources/barvinok-5.158/>; a sibling thread "MafiaELRS" exists at
<https://fpvua.org/threads/mafiaelrs.631/>). Commodity hardware follows: a Ukrainian shop sells an
LR1121 receiver combining a **150-700 MHz** subsystem with a **1.7-2.7 GHz** subsystem on an ESP8285,
tested with MilELRS, modified ELRS and Барвінок-5
(<https://flasharmy.com.ua/prijmach-elrs-433-mgts-150-700-mgts-2-4-ggts-1-7-2-7-ggts-lr1121-dbr1-esp8285-aeronetix>).

Two consequences. First, **the drone-side downlink can be silent**, so a detector must find the
ground transmitter's uplink and the video transmitter rather than waiting for telemetry. Second, an
ELRS detector that sits on 868/915/2400 MHz will miss these links entirely; the search space is
150 MHz to 2.8 GHz. That does not change the decodability picture - every 2.4 GHz ELRS mode remains
detect/classify-only, and the standard 2.4 GHz FHSS table already spans 2400.4-2479.4 MHz, wider than
the E200's 56 MHz instantaneous bandwidth *(verified: verdict 3, ELRS decodability)*.

### 4.2 Where control links actually live: a dated drift

"Азы РЭБ, или коротко о главном" ("EW basics, in short") gives a timeline that is directly usable as
band edges for a sub-GHz energy and chirp detector
([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Азы_РЭБ_или_коротко_о_главном.html)):

| Period | Control band in use |
| --- | --- |
| 2022-2023 | standard 850-925 MHz |
| second half of 2023 | widened to 750-1060 MHz |
| "at present" (2025 post) | 433 MHz and the 415-640 MHz range; example given of a drone on "ELRS 755 MHz" |

The same post warns explicitly not to confuse video-channel frequencies with control-channel
frequencies - a discipline worth keeping in the toolkit's own labels. Hobby-market Russian articles
independently describe 700-750 MHz as "a new promising direction" for long-range FPV control
(<https://modelistam.com.ua/nestandartnye-chastoty-kak-vybrati-dlya-obhoda-pomeh-a-365/>).

### 4.3 Video: far wider than 5.8 GHz, and partly above the E200's ceiling

The consolidated **Таблица частот VTX** ("VTX frequency table") in the techuav mirror is the best
single band list found in any language for video transmitters actually sold into that market
([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ПЛАТФОРМА_FPV/Видеосвязь/Таблица_частот_VTX..html)):

| Block | Channels / notes |
| --- | --- |
| 460-600 MHz | 8 channels |
| 910-1360 MHz | 15 channels, including 1258 and 1280 MHz |
| 1405-1680 MHz | 12 channels |
| 2290-2510 MHz | 12 channels |
| 3310-3495 MHz, 3200-3700 MHz (bands A-E), 3330-3480 MHz (BeastFPV) | the 3.3 GHz family |
| 3700-4150, 4500-4685, 3000-4938 MHz (bands A/B/E/F/r/P/H/U) | - |
| 4867-6184 MHz | the classic A/B/E/F/Raceband plan plus digital rows |
| DJI V1 25 Mbps | 5660, 5695, 5735, 5770, 5805, 5878, 5914, 5839 MHz |
| **DJI O3 10/20 MHz (14/25 Mbps)** | **5669, 5705, 5768, 5804, 5839, 5876, 5912 MHz** |
| **DJI O3 40 MHz (50 Mbps)** | **5677, 5794, 5902 MHz** |
| Walksnail race / 25 / 50 Mbps, HDZero FCC and CE rows | listed alongside |

(The DJI O3 and HDZero rows were re-read directly from the cloned HTML to confirm them.) Per-model
JSON channel and power tables in the same mirror give Foxeer Reaper Infinity 4.9-6.0 GHz 10 W with
64-80 channels, RushFPV 3.3 GHz 16 channels over 3.17-3.47 GHz at 2 W, iFlight BLITZ 3.3 GHz 5
channels over 3.25-3.37 GHz, and AKK Alpha 5 W 5.3-5.9 GHz 64 channels.

Above that, two developments push past the E200:

* **FPV video transmitters above 6.2 GHz** were reported in use, with the note that "these
  frequencies are above the range of all drone detectors ZOV, BULAT, H9LP, Skydroid", leaving only
  Дроноскоп 4.7 (to 7.3 GHz) or an Arinst SSA R3
  ([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Сегодня_зафиксировано_применение_противником_FPV_дронов_с_видеопередатчиками_выше_6.2_ГГц_в_тыловых_.html)).
  The AD9361 stops at 6 GHz, so this needs a companion sweep instrument or a downconverter.
* **OpenIPC digital video**: RTL8812 Wi-Fi chips confine current units to 4900-5990 MHz, but the
  firmware is modified so the channel bandwidth "can even be 10 MHz", and the same system can run on
  3.55-3.7 GHz or 5.925-7.125 GHz. The post's conclusion - "your drone detector does not see these
  drones" - is the operational point
  ([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Большинство_выбрало_пост_про_цифру_оппонентов.html)).
  A 10 MHz-wide 802.11 signal at a non-standard centre is exactly the case a template matcher on
  20 MHz Wi-Fi channels will miss.

### 4.4 Analog video is being hidden, so classify on structure

"Скрываем аналоговый видеосигнал" ("Hiding the analog video signal") documents two techniques in
field use: a **video inverter** (reversible with another inverter) and a **video scrambler**
("practically impossible to decode in the available time"), both fitted as TX/RX pairs to the VTX and
VRX, with the author recommending the scrambler
([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ПЛАТФОРМА_FPV/Видеосвязь/Скрываем_аналоговый_видеосигнал..html)).
A detector that proves presence by producing a recognisable picture - the Chuyka/HUNTER approach -
degrades against this, while an FM-video **spectral** signature (line-rate structure, deviation) does
not. That is consistent with the independent finding that analog FPV keeps its energy in a
luma-driven quasi-static FM core, so a 10 MSPS capture is enough for detection and for a usable NTSC
picture *(verified: verdict 5, analog FPV bandwidth)*.

### 4.5 Links that are not ELRS at all

"Что такое Спецсвязь Гермес?" ("What is Hermes special comms?") describes a Russian domestic
control link that is explicitly **not** a fork of ELRS or TBS: its own protocol with AES packet
encryption and IP addressing, "multi-band link on one drone/robot with FHSS up to 400 MHz" (antenna
and FHSS settings up to 100 MHz), control and video frequencies changeable from the operator's radio
via a Lua script, multi-bind, hibernation for "ambush drones", wired and airborne repeaters, and a
modem with USB/UART/Ethernet
([techuav mirror](https://github.com/techuav/techuav.github.io/blob/main/docs/ТЭЧ_БпЛА_FPV/Чат/Что_такое_Спецсвязь_Гермес.html)).
A signature classifier built only from ELRS/CRSF/DJI templates will never label this. The toolkit
needs an explicit **"unknown wide-FHSS"** class whose hop statistics are gathered by sweeping, not by
assuming the hop set fits inside one 20 MHz window.

### 4.6 DroneID can be switched off or faked in the field

The same mirror carries a Russian re-flash registry for DJI aircraft listing drone-name commands
`aeroscope_off` (the drone is not visible on AeroScope and sends no position, home point or operator
data), `aeroscope_random`, `aeroscope_z` and `aeroscope_heart` (broadcast pseudo-random or
shape-drawing fake coordinates over DRONE ID), and firmware modifications described as
"отключены DRONE ID, OpenDroneId, NFZ" (DRONE ID, OpenDroneID and no-fly zones disabled)
*(verified: verdict 4, DJI generation coverage; local read of
`docs/ПЛАТФОРМА_FPV/Прошивка/РЕЕСТР_ПРОШИВОК_ДЛЯ_КВАДРОКОПТЕРОВ_DJI.html` and
`ПРОШИВКА_И_ПО_ДЛЯ_М3_(МАВИК_3).html` in <https://github.com/techuav/techuav.github.io>)*. DroneID is
unauthenticated, so this is cheap. For AERIX it means an observation network must never treat
DroneID or Remote ID absence as evidence of absence, and never treat a DroneID position as
trustworthy without RF corroboration.

### 4.7 The resulting requirement deltas

| Frontline observation | Requirement it creates | Where it lands |
| --- | --- | --- |
| ELRS forks across 150 MHz - 2.8 GHz with arbitrary 20 MHz custom bands | Sub-GHz and 1-2 GHz energy/chirp sweep, not fixed 868/915/2400 MHz channels | [ADR-0010](../docs/decisions/ADR-0010-band-coverage.md) wide-sweep profile |
| Telemetry moved or disabled | Detect the ground transmitter uplink and the VTX, not the aircraft downlink | [landscape.md](landscape.md) RC section |
| Analog video from 460 MHz to 6184 MHz, 1.2/3.3 GHz common | Video sweep must cover far more than the 5.8 GHz plan; all of it except >6 GHz fits the E200's 70 MHz-6 GHz range | [signal-reference.md](signal-reference.md) video tables |
| Video above 6.2 GHz; OpenIPC on 5.925-7.125 GHz | Out of E200 reach; document the blind spot, do not paper over it | [hardware-e200.md](hardware-e200.md) |
| 10 MHz-wide non-standard Wi-Fi video | Do not assume 20/40 MHz Wi-Fi channel templates | [signal-reference.md](signal-reference.md) |
| Inverted/scrambled analog video | Classify on FM spectral structure, not on decoded picture | [ADR-0007](../docs/decisions/ADR-0007-detection-pipeline-heuristics-before-ml.md) |
| Proprietary AES/FHSS links (Hermes) | An "unknown wide-FHSS" class and sweep-based hop statistics | classifier design |
| DroneID disabled or spoofed by re-flash | Never treat identity broadcast as ground truth; corroborate with RF | [ADR-0008](../docs/decisions/ADR-0008-relation-to-aerix-observation-contract.md) |
| Fibre-optic FPV drones emit nothing | RF detection has a hard floor; passive radar is the only published counter | [ADR-0009](../docs/decisions/ADR-0009-localisation-deferred.md) |

A caveat the Russian lens itself raised and this document repeats: **relevance to the Netherlands is
asymmetric.** The 433/700-1000 MHz control forks and 1.2/3.3 GHz video are frontline-driven and rare
in European hobby use. A security-oriented deployment should still be able to flag energy there, but
the default scan profile should not be built around them, and the legality of listening in those
bands in the Netherlands was not assessed here - see [regulatory.md](regulatory.md) and
[ADR-0011](../docs/decisions/ADR-0011-legal-posture.md).

---

## 5. What to take and what to leave

| Item | Verdict | Why |
| --- | --- | --- |
| MicroPhase `source_cn/` docs (clock discipline via `ad5660mp`, 2r2t procedure, UHD probe, port table) | **Take** | Vendor ground truth, verified, and more specific than the English pages |
| DroneRFa Table 4 hop-block features | **Take** | Hand-written detection rules that need no training data |
| DroneRFa 10 ms window-length finding | **Take** | Sets the buffering budget for any E200 classifier |
| RF-Vision-UAV-Tracker's S1 kurtosis pre-scan and S3 calibration / PSR / CFS / persistence design | **Take the design, not the code** | MIT-licensed, but the numbers come from a PlutoSDR loopback rig; re-derive thresholds on real captures. The `ocusync-phy` spacing it relies on is unverified round-1 |
| luolitao Remote ID decoders (GB 42590 / GB 46750 discrimination rules) | **Take as reference** | The only open implementations; resolve the timestamp discrepancy from the standard text first |
| Chinese commercial C-UAS feature list (300-6000 MHz, signature library, amplitude DF, TDOA, black/white lists) | **Take as a schema checklist** | A ready specification of what a signal library should contain |
| techuav VTX and control-band tables | **Take** | The widest empirical band list found in any language |
| MilELRS/Барвінок-5 frequency behaviour | **Take** | Defines the search space for frequency-agile RC |
| leegang12's "O1-O4 CRC correct" claim | **Leave** | No code, snippet-only, and contradicted for O4 by verdict 4 |
| Chinese method papers' accuracy figures | **Leave** | Snippet-only, no grouped splits, synthetic low-SNR |
| SE-DCNet / RF-TCNet absolute accuracies | **Leave**, keep the architecture comparison | Leaky splits confirmed in `prepare_labels.py` *(verified: verdict 8)* |
| SkySweep32 RSSI tiering | **Leave** | Explicitly does not identify anything; useful only as a baseline to beat |
| passive-sdr-radar | **Park** | Good skeleton, but its own TODO says real data is not connected; revisit if RF-silent drones become a priority |
| Vendor range and price claims (Bulat 1.5 km, Chuyka 4 km, Alissum 1 km) | **Leave as context** | Marketing, uncontrolled conditions |

---

## Gaps

Drawn from `gaps_or_open_questions` in the three foreign lenses and from the verdicts.

**Chinese community**

1. No genuine Chinese-community hands-on content about the ANTSDR E200 itself surfaced. Every Chinese
   hit was MicroPhase's own documentation or an English site, so Chinese user experience with E200
   firmware and streaming remains unknown.
2. The IPEX connector is not labelled in the text layer of `ANT-E200_Public.pdf`. Which AD9361 port
   is routed there and whether it has its own switch or balun must be confirmed from the schematic
   page images or from MicroPhase.
3. leegang12's DroneID/Aeroscope series is snippet-only: no code, no way to verify the O1-O4 CRC
   claim, the four packet types or the 5 dB demodulation threshold without downloading the CSDN pages.
4. The byte-level relationship between GB 42590-2023 broadcast Remote ID and ASTM F3411 / Open Drone
   ID is unconfirmed, and the two open GB 46750 implementations disagree on timestamp encoding.
5. No Chinese source gave per-model DJI spectral signature tables (bandwidth 10/20/40 MHz, hop dwell,
   channel lists) for O3/O4 or Mini 3 / Mavic 3; only marketing-level band lists were found.
6. No Taobao or 闲鱼 price or SKU for a MicroPhase GPSDO, IPEX-to-SMA pigtail or 10M/PPS MMCX cable
   surfaced; accessory sourcing must be checked directly on the Taobao listing.
7. The MIIT UAV band allocation article may list sub-GHz and 1.4 GHz allocations used by Chinese
   industrial drones that a EU-centric scan misses; the numbers were not in the snippet.
8. DroneRFb-DIR and the Chinese dataset roundup are on blocked domains; download terms, and whether
   the IQ files are usable at E200 rates without heavy resampling, are unknown.
9. The "single video module occupies 8 MHz" claim conflicts with the DJI SDK 10/20 MHz settings and
   with the measured ~18 MHz occupied bandwidth; unresolved.

**Chinese academic**

10. Authors and affiliations of JEIT230302 (multi-dimensional features) and JEIT241111 (MFCC+GRU)
    could not be retrieved; `jeit.ac.cn` and `sciengine.com` are blocked.
11. No CNKI or 万方 master's theses surfaced through web search; a manual CNKI query is needed to
    cover the thesis literature the lens was meant to reach.
12. It is unknown whether DJI or other Chinese-brand drones sold in the EU ever emit GB 42590 or
    GB 46750 frames alongside ASD-STAN. Worth sniffing a recent unit for the `0xFF` / `0x20` header.
13. No Chinese-language work using the ANTSDR E200 or any MicroPhase board for drone detection was
    found; Chinese authors overwhelmingly use NI USRP-2955, N210 or B200.
14. No Chinese open drone-RF dataset outside the Zhejiang University family was identified.
15. SciDB downloads require an account and DroneRFa segments are >= 100 M samples each in `.mat`;
    access speed from the Netherlands is untested.
16. The 2019 anquanke blind-analysis post could not be fetched; its O2 claims are snippet-only.

**Russian and Ukrainian**

17. **No Russian- or Ukrainian-language open-source SDR/IQ-level drone signal classifier, dataset or
    GNU Radio flowgraph was found.** The open scene is ESP32/RSSI hardware or KrakenSDR passive radar;
    the ML claims (Alissum, Дроноскоп) are closed commercial products.
18. The MilELRS `DETECTOR`, `EW_SCANNER` and `CUSTOM_FREQ2` PDFs referenced in the manual are not in
    the techuav dump, so what the "PRFR signal analysis / DF" mode actually computes on an SX1276
    remains unknown.
19. The Ukrainian detector "Кажан" could not be found at all; Chuyka 3.0 and "Перець" specifications
    come only from a Russian mirror or shop snippets and were not verified against a Ukrainian primary
    source (`fpvua.org`, `smell.co.ua`, `militarnyi.com` are blocked).
20. CyberLeninka and eLibrary papers (SDR direction finder, UAV detection survey, TDOA articles) were
    reachable only as abstracts; none appears to publish code or drone RF data.
21. No evidence was found of Russian or Ukrainian community use of ANTSDR / PlutoSDR / AD9361 hardware
    for drone detection; HackRF, RTL-SDR, tinySA and Arinst dominate.
22. The Telegram-native DIY detector scene (schematics posted as images and videos) is not reachable
    from this environment; only the techuav mirror and shop snippets represent it.
23. Legality of receiving in the 433/700-1000 MHz and 1.2/3.3 GHz bands in the Netherlands was not
    assessed in this lens.

**Carried over from the verification pass**

24. `o4-firmware-channels` - the E200 O4 DroneID firmware channel set, 1r1t 61.44 MSPS path clock and
    the legacy FPGA correlator `/dev/my-axi-droneid-filter0` - is **unverified round-1**.
25. `ocusync-phy` - OcuSync 2 at 15 kHz spacing with FFT 2048/1024 and CP 144/72, O3/O4 at about
    30 kHz spacing, ~9 MHz 99 % bandwidth, 5 ms periodicity on a Mini 5 Pro, and CP autocorrelation as
    the separator from Wi-Fi's 312.5 kHz - is **unverified round-1**. Every cyclostationary number in
    section 2.3 inherits that uncertainty.
26. The Chinese CSDN report of decoding a **Mavic 2 Pro** with a B200 contradicts the verified finding
    that open decoders do not support Mavic 2 parameters; snippet-only, unresolved.

The corresponding priority download list for each of these is in the "Wanted downloads" section of
[datasets.md](datasets.md) and in [sources.md](sources.md); the highest-value items from this
document are the CSDN leegang12 series, `4code.ru/publications/band5800`, the smell.co.ua build log,
the Barvinok-5 primary page, the GB 46750-2025 standard text and the DroneRFb-DIR dataset.
