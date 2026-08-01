# test_main_window_lang_combo.py -- dev#595 再修正の実証テスト。
#
# 背景: PR #608 は「state="readonly"のttk.Comboboxはtextvariableをコンストラクタ
# で渡すだけでは初期表示に反映されない」という見立てで .current() 呼び出しを
# main_window.py へ追加したが、その後もオーナー実機で「Languageコンボの初期表示
# が空」が再現した(2026-08-01)。本ファイルは非表示Tkルート(state=withdraw、
# 画面には一切表示しない。common brief wp_v232_common.mdの例外条項どおり)での
# 実証により、その見立てが誤りだったことを確認した過程をテストとして残す。
#
# 実証された真因: main_window.py _build_widgets() 内の `lang_var`
# (tk.StringVar)がこの関数のローカル変数のままで、self.*のどこにも保持されて
# いなかった。ttk.Comboboxのtextvariableは「Tcl変数名の文字列」を保持するだけで
# Pythonオブジェクトへの参照は握らないため、_build_widgets()がreturnした時点で
# lang_varの参照カウントが0になりCPythonが即座に破棄する。tkinter.Variable.__del__
# は破棄時に対応するTcl変数をglobalunsetvarで消すため、ウィジェットは存在しない
# 変数を指すことになり表示が空欄になる(combo.get()==""、combo.current()==-1)。
# .current()呼び出しの有無はこの壊れ方に無関係(下のtest_lang_combo_survives_
# without_current_callで負の対照として確認)。
#
# 修正: main_window.py _build_widgets() で `self._lang_var = lang_var` を追加し、
# 生存参照を保持する(すぐ下にある auto_apply_var: L.741/751相当の
# `self._auto_apply_var = auto_apply_var` と同じ、この関数内で既に使われている
# 慣例に合わせただけ)。
#
# tkの実ウィンドウは一切表示しない(root.withdraw()、common brief契約どおり)。
from __future__ import annotations

import gc
import os
import sys
import tkinter as tk
from tkinter import ttk

import pytest

_APP_PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_PY_DIR not in sys.path:
    sys.path.insert(0, _APP_PY_DIR)

import i18n  # noqa: E402
from ui import main_window as mw  # noqa: E402


def _make_fake_self(root: tk.Tk, app_root: str) -> mw.MainWindow:
    """MainWindow.__init__を経由せず_build_widgets()だけを実行するための最小
    フェイクインスタンス(test_gui_log_robustness.pyの「束縛前メソッドをフェイク
    selfへ直接呼ぶ」パターンを踏襲)。__init__本体(起動時セルフチェック・
    他MOD検出用バックグラウンドスレッド・drag&dropのOSフック等)は今回の検証
    対象(langComboの初期表示)と無関係かつ重い副作用を伴うため、あえて経由
    しない。_build_widgets()が直接読み書きするインスタンス属性
    (root/app_root/widgets/_tooltips)だけを用意すれば足りる
    (他のself.foo参照は同関数内で新規に代入されるか、クラスメソッドの
    参照であり実行時に問題は起きない)。"""
    self = mw.MainWindow.__new__(mw.MainWindow)
    self.root = root
    self.app_root = app_root
    self.widgets = {}
    self._tooltips = []
    return self


@pytest.fixture
def hidden_root():
    root = tk.Tk()
    root.withdraw()  # 画面には一切表示しない(common brief契約の例外条項どおり)
    try:
        yield root
    finally:
        root.destroy()


def test_lang_combo_shows_current_language_after_build(hidden_root, tmp_path):
    """本修正の受入条件そのもの: 初回起動(設定ファイル無し)相当の状態で
    実際の_build_widgets()を呼び、その関数がreturnした「後」でlangComboの
    表示がi18n.current_langと一致し続けることを検証する。関数のreturn後に
    確認するのが肝(lang_varはローカル変数なので、関数内で確認するだけでは
    dev#595のGCバグを見逃す)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("ja")
        self = _make_fake_self(hidden_root, str(tmp_path))

        mw.MainWindow._build_widgets(self)
        # CPythonは参照カウントが0になった時点で即座に破棄するため本来
        # gc.collect()は不要だが、環境差(PyPy等)を気にせず明示しておく。
        gc.collect()
        hidden_root.update_idletasks()

        combo = self.widgets["langCombo"]
        assert combo.get() == "日本語"
        assert combo.current() == 0
        assert hasattr(self, "_lang_var"), (
            "self._lang_var が無い(dev#595の修正が外れている)。"
            "lang_varがローカル変数のままだとGCで即破棄され、Tcl側の裏変数が"
            "unsetされてreadonly Comboboxの表示が空になる。"
        )
    finally:
        i18n.clear_registry()


def test_lang_combo_survives_without_current_call(hidden_root, tmp_path):
    """PR #608の見立て(「.current()を呼ばないと初期表示が空になる」)が
    誤りだったことの直接証明。textvariableとして渡したStringVarへの生存参照
    さえ保持されていれば、.current()を一切呼ばなくてもreadonly Comboboxは
    正しく表示される(main_window.pyを介さない最小構成での確認。
    _build_widgets()自体は.current()を引き続き呼ぶ設計のまま変えていない
    ため、実コードパスの検証は上のtest_lang_combo_shows_current_language_
    after_buildが担う)。"""
    lang_var = tk.StringVar(value="English")
    combo = ttk.Combobox(
        hidden_root, textvariable=lang_var, values=["日本語", "English"],
        state="readonly",
    )
    # .current(...) を意図的に呼ばない
    kept = lang_var  # 生存参照を保持するだけ
    del lang_var
    gc.collect()
    hidden_root.update_idletasks()

    assert combo.get() == "English"
    del kept  # 後片付け(次アサーションの対照用に明示的に解放)


def test_lang_combo_goes_blank_if_reference_dropped(hidden_root, tmp_path):
    """負の対照: 実コードパス(_build_widgets())が作ったlangComboについて、
    dev#595の修正そのもの(self._lang_var)を後から取り除くと、同じウィジェット
    が実際に空欄化することを示す。.current()呼び出しは残したままなので、
    「表示が消えるかどうか」はlang_varへの生存参照の有無だけで決まることが
    ここで確認できる(PR #608の見立てが的外れだったことの反証)。"""
    i18n.clear_registry()
    try:
        i18n.set_language("en")
        self = _make_fake_self(hidden_root, str(tmp_path))

        mw.MainWindow._build_widgets(self)
        gc.collect()
        hidden_root.update_idletasks()
        combo = self.widgets["langCombo"]
        assert combo.get() == "English"  # 修正が効いている状態を先に確認

        del self._lang_var  # 修正を取り除く(PR #608だけが入っていた状態を再現)
        gc.collect()
        hidden_root.update_idletasks()

        assert combo.get() == "", "修正を外したのに空欄が再現しない(想定と矛盾)"
        assert combo.current() == -1
    finally:
        i18n.clear_registry()
