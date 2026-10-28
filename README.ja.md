# CATFOOD Atom + Boost for ChatGPT v0.5.55

[English README](README.md)

CATFOOD Atom + Boost は、ChatGPT Web が重く感じたときに、まず一つの問いへ答えるための小さなローカルツールです。

**「いま本当に遅いのは、どこなのか？」**

ブラウザ側の性能をローカルで観測し、ネットワーク待ちと画面側の引っかかりを分離して見せます。Boost は保守的に扱い、ChatGPT のリクエスト本文を書き換えたり、レート制限を回避したり、会話内容を外部の解析サービスへ送ったりしません。

## 何が見えるの？

- API リクエスト時間と TTFB
- 429 を含む HTTP ステータス数
- API リクエストの集中（burst）と同時実行
- 入力操作の遅延
- Long Animation Frame と表示中ページのメインスレッド負荷
- 画面のカクつき・長い停止・レイアウトの揺れ
- 表示中タブとバックグラウンドタブの負荷を分離

解析画面では専門用語を隠さず、その横に普通の言葉で意味も表示します。

## Boost は何をするの？

手動の Boost 設定は**初期状態ではすべて OFF**です。

現在ひとつだけ実運用へ昇格した適応動作があります。表示中のページで大きなアニメーションフレーム負荷を観測したときだけ、約 1.5 秒間アニメーション／トランジションの仕事を一時的に減らし、その後は自動で通常表示へ戻します。

試して負けたものは勝手に有効化しません。

- backdrop blur 削減: 却下
- instant scroll 強制: 却下（有効な差がほぼなし）
- offscreen message culling: 実際に近いストリーミング負荷で悪化したため runtime から引退

## 観測済みベンチマーク

これは開発時の実測であり、**すべてのPC・すべてのセッションで同じ改善率を保証する数字ではありません**。

| 実験 | 観測結果 |
| --- | ---: |
| 一時 reduce-motion 候補、実 ChatGPT 5 matched pairs | FCP 中央値 約9.8%短縮、Load 約6.1%短縮 |
| MutationObserver を count-only 化した mutation-heavy synthetic fixture | observer callback の仕事 約29%削減 |
| v0.5.55 release freeze 直前の live delivery | telemetry duplicate 0件 |

見た目だけ速そうな案でも、A/B を繰り返して負けたものは採用しない方針です。

## プライバシー

CATFOOD Atom + Boost は次のものを保存しません。

- 会話本文
- リクエスト本文
- レスポンス本文
- Cookie
- Authorization header
- 生の URL
- Query string

ローカル計測サービスは loopback のみに待ち受けます。

## 必要なもの

- Python 3
- unpacked Manifest V3 extension を読み込める Chromium 系デスクトップブラウザ
- Linux / macOS / Windows 10/11

通常利用に Node.js、npm、Docker、クラウドアカウントは不要です。

## インストール

### Linux / macOS

```bash
python3 install.py
```

### Windows PowerShell

```powershell
py -3 .\install.py
```

その後、

1. ブラウザの拡張機能管理画面を開く。
2. **デベロッパーモード**を有効にする。
3. **パッケージ化されていない拡張機能を読み込む / Load unpacked** を選ぶ。
4. このリリースに入っている `extension` フォルダを指定する。
5. すでに開いている `chatgpt.com` のタブを一度だけ再読み込みする。

## 動作確認

```bash
python3 status.py
```

ローカルサービスとブラウザ拡張の両方が v0.5.55 と表示されれば一致しています。

## リリースの完全性

配布 ZIP は runtime を一度 freeze してから生成します。PRIVATE の実験ログ、失敗台帳、研究 fixture、バックアップ、Python bytecode は fail-closed の release gate で除外します。ZIP と一緒に SHA-256 を生成します。

## ライセンス

MIT。`LICENSE` を参照してください。
