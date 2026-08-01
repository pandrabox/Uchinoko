# i18n.py -- Strings.S/F 相当(旧 app\DiveToPalworld.cs の Strings 静的クラス)。
#
# 移植元: app\DiveToPalworld.cs
#   - Strings.Table            (L.39-265, "187+alpha" のうち UI文字列本体)
#   - Strings.ProgressLabels   (L.314-335, ##PROGRESS## 由来ラベルの辞書。
#                                Tableとは別辞書=名前空間分離、原文どおり踏襲)
#   - Strings.S/S(key,lang)/F  (L.269-302)
#   - RegisterI18nText/RegisterI18nTip/ApplyLanguage (L.856-901)
#     -> 本ファイルの register()/apply_language() が Python 版の対応表(§4.4)
#
# 翻訳データ本体は i18n_data.json (DESIGN.md §2.6 の推奨どおり外部データ化)。
# ここには「訳文を選ぶ・差し替える」ロジックのみを置き、訳文そのものは書かない
# (訳文の創作・改変禁止。i18n_data.json は DiveToPalworld.cs から機械的に抽出した
# ものであり、本モジュールが手を加えることはない)。
#
# Strings.ProgressLabelTemplates(regex テンプレート、L.352-362)はここでは
# 移植していない(可変部を含む動的な翻訳"ロジック"であり、進捗リレー機構と
# 一体で pipeline_runner.py 側(WP-A2)が担う想定。DESIGN.md §5.2 WP-A1 行の
# 「i18n.py + i18n_data.json」はTable/ProgressLabels二辞書の移植を指すと解釈した)。

from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional

# Lang enum 相当(DiveToPalworld.cs L.24: Ja=0, En=1, Ko=2, ZhTW=3, ZhCN=4)。
# 内部辞書キーは i18n_data.json / DESIGN.md 本文の表記に合わせ "zhTW"/"zhCN"
# (キャメルケース、ハイフン無し)。ディスク上の設定ファイル(settings_language.txt)
# はC#実装がハイフン入り("zh-TW"/"zh-CN")で書くため、FILE_LANG_CODES で変換する。
LANGS = ["ja", "en", "ko", "zhTW", "zhCN"]

# settings_language.txt に書かれるコード(DiveToPalworld.cs LangToCode/TryParseLangCode
# L.784-807 と1:1)。langCombo の表示順(日本語/English/한국어/繁體中文/简体中文、
# L.1230)も LANGS と同じ並び。
FILE_LANG_CODES = {"ja": "ja", "en": "en", "ko": "ko", "zhTW": "zh-TW", "zhCN": "zh-CN"}
FILE_CODE_TO_LANG = {v: k for k, v in FILE_LANG_CODES.items()}

# langCombo の表示ラベル(自称、翻訳しない。L.1227-1230のコメントどおり)
LANG_DISPLAY_NAMES = ["日本語", "English", "한국어", "繁體中文", "简体中文"]

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n_data.json")


def _load_data(path: str = _DATA_PATH) -> tuple[dict, dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw = dict(raw)  # 呼び出し元が誤って共有辞書を書き換えないようコピー
    progress_labels = raw.pop("_progress_labels", {})
    return raw, progress_labels


TABLE, PROGRESS_LABELS = _load_data()

current_lang: str = "ja"


def set_language(lang: str) -> None:
    """現在の表示言語を切り替える(Strings.Current相当)。不正な値はjaへ。"""
    global current_lang
    current_lang = lang if lang in LANGS else "ja"


def _pick(values: dict, lang: str) -> Optional[str]:
    """5言語dictから指定言語を選ぶ(PickFromArray L.296-302相当)。
    指定言語が無い/空ならja(索引0)へ、それも空ならNone。"""
    v = values.get(lang)
    if v:
        return v
    v0 = values.get("ja")
    return v0 if v0 else None


def S(key: str, lang: Optional[str] = None) -> str:
    """キーの文字列を返す。未知キー/データ欠落でも例外を投げず可視マーカー
    "??key??" を返す(Strings.S L.269-285と同じ設計方針)。"""
    values = TABLE.get(key)
    if values is None:
        return "??" + key + "??"
    picked = _pick(values, lang or current_lang)
    if picked is None:
        return "??" + key + "??"
    return picked


def F(key: str, *args: Any) -> str:
    """string.Format相当(Strings.F L.287-290)。{0}/{1}...プレースホルダは
    Pythonのstr.formatと同じ記法なので、翻訳データ側は無改変で使える。"""
    text = S(key)
    return text.format(*args) if args else text


def detect_lang_from_culture(culture_name: Optional[str]) -> str:
    """DetectLangFromCulture() 相当(DiveToPalworld.cs L.766-779。dev#532方針A
    WP-A11/dev#549で移植)。純粋関数: CultureInfo名(例 "ja-JP")文字列から
    内部言語コード(LANGSの表記、"zhTW"/"zhCN"はキャメルケース)を判定する。
    実際のOSロケール取得(CultureInfo.CurrentUICulture.Name相当)は
    呼び出し側(main_window.pyの起動時判定)が担う(C#のDetermineInitialLang
    L.817-831と同じ役割分担。この関数自体はテスト容易性のため文字列入力のみに
    依存する、元のdocstringどおり)。

    ja→ja / ko→ko / zh-Hant系(zh-TW/zh-HK/zh-MO/Hant)→zhTW /
    zh(その他、Hans系含む)→zhCN / それ以外・空・不正→en。
    """
    if not culture_name:
        return "en"
    n = culture_name.lower()
    if n.startswith("ja"):
        return "ja"
    if n.startswith("ko"):
        return "ko"
    if n.startswith("zh"):
        if "hant" in n or "-tw" in n or "-hk" in n or "-mo" in n:
            return "zhTW"
        return "zhCN"  # Hans系、またはバリアント無しの単なる"zh"
    return "en"


def translate_progress_label(raw: str, lang: Optional[str] = None) -> str:
    """##PROGRESS##由来の生ラベル文字列を翻訳する(TranslateProgressLabelFrom
    L.372-378の単純固定文字列版のみ。可変部を含むProgressLabelTemplates側の
    正規表現マッチはpipeline_runner.py(WP-A2)側で扱う想定)。
    辞書に無ければ原文をそのまま返す(ブラックリスト方式、L.309のコメントどおり
    「未知ラベル=無表示」を作らない)。"""
    values = PROGRESS_LABELS.get(raw)
    if values is None:
        return raw
    picked = _pick(values, lang or current_lang)
    return picked if picked is not None else raw


# ---------------------------------------------------------------------------
# i18n再登録機構(DESIGN.md §4.4 / DiveToPalworld.cs RegisterI18nText・
# RegisterI18nTip・ApplyLanguage L.856-901相当)。
#
# C#版は「(Control, key)」のペアをリストへ憶えておき、ApplyLanguageが全走査して
# Text/Tooltipを差し替える設計。Python版もウィジェットの種類を問わない汎用形で
# 同じ仕組みを再現する: register()に「この値をどう書き込むか」のsetterを渡す
# ことで、tkinterのLabel/Button(config(text=...))だけでなくツールチップ表示用の
# 補助オブジェクト等にも同じ登録簿を使い回せる。
# --check-apply-language(DiveToPalworld.cs L.5907)が課している「登録数の厳密
# 一致」の検査粒度は、A7(自己診断移植)で本モジュールのregistryをそのまま
# 検査対象にすれば踏襲できる。
# ---------------------------------------------------------------------------

Setter = Callable[[Any, str], None]

_registry: list[tuple[Any, str, Setter]] = []


def default_text_setter(widget: Any, text: str) -> None:
    widget.config(text=text)


def register(widget: Any, key: str, setter: Setter = default_text_setter) -> None:
    """ウィジェットをi18n登録簿へ加え、直ちに現在言語の訳文を反映する。"""
    _registry.append((widget, key, setter))
    setter(widget, S(key))


def registry_size() -> int:
    """--check-apply-language相当の検査で使う登録数(A7移植先で利用予定)。"""
    return len(_registry)


def clear_registry() -> None:
    """テスト用: 登録簿を空にする(pytestのウィジェット再生成間の汚染防止)。"""
    _registry.clear()


def apply_language(lang: str) -> None:
    """言語切替の即時反映(ApplyLanguage L.874-901のうち、Text/Tooltip再適用
    部分に相当)。ウィンドウタイトル・状態依存表示の再計算はmain_window.py側の
    呼び出し元が担う(このモジュールは「登録済みのkey付きウィジェット」の
    再適用にのみ責任を持つ、既存の役割分担どおり)。"""
    set_language(lang)
    for widget, key, setter in _registry:
        try:
            setter(widget, S(key))
        except Exception:
            # 破棄済みウィジェット等はスキップ(画面を固めるより手がかりを残す方を選ぶ、
            # Strings.Sの設計方針を再登録機構にも適用)
            pass
