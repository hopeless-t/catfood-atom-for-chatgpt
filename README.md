# CATFOOD Atom + Boost for ChatGPT

**Current release: v0.5.55**

ChatGPT Web が重いときに、**何が起きているのかをローカルで観測して、実際に効く改善だけを残す**ための小さなツールです。

CATFOOD Atom は性能信号を観測・分析します。CATFOOD Boost は、実測で有効性を確認できた改善だけを慎重に使います。

[English](#english)

## 日本語

### できること

- ChatGPT API の TTFB: median / average / p95 / max
- HTTP 429 の検出
- API request burst / 同時リクエストの観測
- 遅い成功GETが server wait 側に寄っているかの診断
- Interaction latency
- Long Animation Frame / UI stall の観測
- foreground / background tab 負荷の分離
- layout shift の観測
- ローカル分析画面
- ACK付き telemetry delivery と duplicate batch 検出
- optional Boost controls

### Boost

手動の Boost 設定は基本的に **OFF** です。

速そうだから有効化するのではなく、実測で有効性を確認できたものだけを残します。

現在の主な状態:

- Reduce backdrop blur: OFF
- Force instant scroll: OFF
- Offscreen message culling: RETIRED
- Manual reduce motion: OFF
- Adaptive motion pressure response: ENABLED

Adaptive motion は、重い描画フレームが実際に観測されたときだけ一時的に animation / transition を抑制し、その後自動的に通常表示へ戻ります。

### 実測例

以下は開発中の特定 workload での観測結果です。すべてのPC・すべてのChatGPT sessionで同じ改善を保証するものではありません。

- real ChatGPT の matched A/B 5組で reduce-motion candidate は median FCP 約 **9.8%改善**、median Load 約 **6.1%改善**
- mutation-heavy synthetic workload では MutationObserver callback work を約 **29%削減**
- v0.5.55 の live readback では duplicate telemetry batches **0**

効果がほぼ無かった instant scroll や、悪化した offscreen message culling などは採用していません。

### 設計思想

CATFOODは、派手な高速化機能を増やすことよりも、
**実際の利用環境で観測された実在の問題をどうしたら減らせるか**を重視しています。

効果が確認できない最適化や、別の問題を増やす変更は採用しません。

……その結果、速くなりました。

### Privacy

CATFOOD Atom は以下を保存しません。

- 会話本文
- prompt / response 本文
- request / response body
- Cookie
- Authorization header
- raw URL
- query string

ローカルserviceは loopback (`127.0.0.1:8767`) のみを使用します。

### Install

Linux / macOS:

```bash
python3 install.py
```

Windows PowerShell:

```powershell
py -3 .\install.py
```

その後、Chromium系browserの拡張機能画面で Developer mode を有効にし、**Load unpacked** から `extension` folder を選びます。

確認:

```bash
python3 status.py
```

---

## English

CATFOOD Atom + Boost is a small local tool for diagnosing real performance problems in ChatGPT Web and keeping only improvements that prove useful in measurement.

### What it can show

- ChatGPT API TTFB: median / average / p95 / max
- HTTP 429 responses
- API request bursts and concurrency
- Diagnosis of slow successful GETs dominated by server wait
- Interaction latency
- Long Animation Frames / UI stalls
- Foreground vs background tab load
- Layout shifts
- Local analysis UI
- ACKed telemetry delivery with duplicate detection
- Optional Boost controls

### Boost

Manual Boost controls are **OFF by default**.

CATFOOD does not enable an optimization just because it sounds faster. Ideas that fail measurement are left disabled or retired.

When severe visual-frame pressure is actually observed, the adaptive motion response may reduce animations/transitions temporarily and restores them automatically afterward.

### Observed results

Development measurements, not guarantees for every machine or session:

- Five matched real-ChatGPT A/B pairs for the reduce-motion candidate showed about **9.8% better median FCP** and **6.1% better median Load**.
- A mutation-heavy synthetic workload showed about **29% less MutationObserver callback work** after simplifying the observer path.
- The live v0.5.55 readback showed **0 duplicate telemetry batches**.

### Design principle

CATFOOD prioritizes reducing real problems observed in actual use over adding impressive-looking optimization features.

Changes that do not show useful results, or that create larger problems elsewhere, are not adopted.

The result happened to be a faster system.

### Privacy

CATFOOD Atom does not store conversation text, prompt/response bodies, cookies, authorization headers, raw URLs, or query strings. The local service listens only on loopback (`127.0.0.1:8767`).

### Install

Linux / macOS:

```bash
python3 install.py
```

Windows PowerShell:

```powershell
py -3 .\install.py
```

Then enable Developer mode in your Chromium-based browser, choose **Load unpacked**, and select the `extension` directory.

Verify with:

```bash
python3 status.py
```

## License

MIT License.

## Disclaimer

Unofficial project. Not affiliated with or endorsed by OpenAI.
