// DiveToPalworld GUI (.NET Framework 4.8 / WinForms / C#5互換)
// ビルド: app\build_app.ps1 (Windows同梱csc.exeを使用、追加ランタイム不要)
//
// ふつうの使い方は3手: VRMを入れる(プレビュー自動生成) → フル変換 → Palworldに適用。
// 肩・影・削除ボーン等は「こだわり設定」を開いた時だけ表示される。
// アバター規約の確認はフル変換時にアバターごとに1回だけ聞く(記憶される)。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.IO.Compression;   // GZipStream(ログ圧縮送信用)。ZipFile(自己更新の展開用、
                                // System.IO.Compression.dll参照が必要)はFIX38で削除した
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace DiveToPalworld
{
    internal enum Lang { Ja = 0, En = 1, Ko = 2, ZhTW = 3, ZhCN = 4 }

    // dev#29(2026-07-29): GUI多言語化(ja/en/ko/zh-TW/zh-CN、オーナー裁定2026-07-29)。
    // ファイル内蔵の文字列テーブル方式(work\rd_29_i18n\PROPOSAL.md の設計に基づく。
    // csc.exe直コンパイル=.resx不可のため)。対象は画面のUI文字列(ボタン・ラベル・
    // ツールチップ・MessageBox・タイトル・問合せダイアログ・更新通知)のみ。
    // 診断ログ本文(AppendLog/BuildDiagnosticsText経由でlogBox・sessionLog・
    // 問い合わせ送信ペイロードへ流れる文字列)は意図的に対象外(別issueで英語固定化
    // される予定。ここでは翻訳しない)。
    // キーの完全性(5言語とも非空)は `Uchinoko.exe --check-i18n <outDir>` で機械検査
    // できる(MainForm.CheckDictionaryCompleteness/CheckI18nCli参照)。
    internal static class Strings
    {
        internal static Lang Current = Lang.Ja;

        internal static readonly Dictionary<string, string[]> Table = new Dictionary<string, string[]> {
            // 2026-07-30 オーナー裁定: 言語選択ラベルは言語によらず英語"Language"に統一
            { "LabelLanguage", new[] { "Language", "Language", "Language", "Language", "Language" } },
            { "TipLanguageSwitch", new[] { "表示言語を切り替えます(すぐに反映されます)", "Switch the display language (applies immediately)", "표시 언어를 전환합니다(즉시 적용됩니다)", "切換顯示語言(立即套用)", "切换显示语言(立即生效)" } },
            { "TitleSubtitle", new[] { "あなたのアバターをパルワールドへ", "Bring your avatar into Palworld", "당신의 아바타를 팰월드로", "讓你的角色模型登入幻獸帕魯", "让你的角色模型登入幻兽帕鲁" } },
            { "LabelAvatar", new[] { "アバター:", "Avatar:", "아바타:", "角色模型:", "角色模型:" } },
            { "BtnBrowse", new[] { "参照...", "Browse...", "찾아보기...", "瀏覽...", "浏览..." } },
            { "FileFilterAvatar", new[] { "アバター (*.vrm;*.fbx;*.prefab)|*.vrm;*.fbx;*.prefab", "Avatar (*.vrm;*.fbx;*.prefab)|*.vrm;*.fbx;*.prefab", "아바타 (*.vrm;*.fbx;*.prefab)|*.vrm;*.fbx;*.prefab", "角色模型 (*.vrm;*.fbx;*.prefab)|*.vrm;*.fbx;*.prefab", "角色模型 (*.vrm;*.fbx;*.prefab)|*.vrm;*.fbx;*.prefab" } },
            { "DlgTitleChooseAvatarFile", new[] { "アバターのファイルを選んでください", "Select an avatar file", "아바타 파일을 선택하세요", "請選擇角色模型檔案", "请选择角色模型文件" } },
            { "HintDragDrop", new[] { "(D&DでもOK)", "(drag & drop OK)", "(드래그 앤 드롭 가능)", "(可拖放檔案)", "(可拖放文件)" } },
            { "BtnFullConvert", new[] { "フル変換(MOD作成)", "Full Convert (Create MOD)", "전체 변환(모드 생성)", "完整轉換(建立 MOD)", "完整转换(创建 MOD)" } },
            { "BtnCancelConvert", new[] { "変換を中止", "Cancel Conversion", "변환 중지", "中止轉換", "中止转换" } },
            { "TitleConfirm", new[] { "確認", "Confirm", "확인", "確認", "确认" } },
            { "ConfirmCancelConvertBody", new[] { "実行中の変換を中止しますか?", "Cancel the running conversion?", "실행 중인 변환을 중지하시겠습니까?", "要中止正在執行的轉換嗎?", "要中止正在进行的转换吗?" } },
            { "StatusPromptVrm", new[] { "VRMファイルを入れてください", "Please add a VRM file", "VRM 파일을 넣어주세요", "請放入 VRM 檔案", "请放入 VRM 文件" } },
            { "BtnBlenderRetry", new[] { "Blenderを再取得", "Retry Blender Setup", "Blender 다시 받기", "重新取得 Blender", "重新获取 Blender" } },
            { "TipBlenderRetry", new[] { "Blenderの初回セットアップをもう一度試みます", "Retries the first-time Blender setup", "Blender 초기 설정을 다시 시도합니다", "重新嘗試 Blender 的首次設定", "重新尝试 Blender 的首次设置" } },
            { "LabelKodawari", new[] { "こだわり設定", "Advanced Settings", "세부 설정", "進階設定", "高级设置" } },
            { "LabelShadowStrength", new[] { "影の濃さ:", "Shadow Strength:", "그림자 농도:", "陰影濃度:", "阴影浓度:" } },
            { "TipShadowBar", new[] { "100%=ふつうの影 / 下げるほど影の中でも明るく見えます(既定30%)。\n反映は「フル変換」または「影のみ更新」の後、ゲーム内で確認できます", "100% = normal shadow / the lower the value, the brighter shadows appear (default 30%).\nCheck the result in-game after \"Full Convert\" or \"Update Shadow Only\".", "100%=일반 그림자 / 낮출수록 그림자 안도 밝게 보입니다(기본값 30%).\n적용 결과는 「전체 변환」 또는 「그림자만 업데이트」 후 게임에서 확인할 수 있습니다", "100%=一般陰影 / 數值越低,陰影內也會顯示得越亮(預設 30%)。\n套用後請在「完整轉換」或「僅更新陰影」執行後於遊戲內確認", "100%=一般阴影 / 数值越低,阴影内也会显示得越亮(默认 30%)。\n应用后请在「完整转换」或「仅更新阴影」执行后在游戏内确认" } },
            { "BtnMatsOnly", new[] { "影のみ更新(高速)", "Update Shadow Only (Fast)", "그림자만 업데이트(빠름)", "僅更新陰影(快速)", "仅更新阴影(快速)" } },
            { "TipMatsButton", new[] { "影の濃さだけを変えてMODを作り直します(1分ほど。フル変換は6分ほど)。\nこのアバターを一度「フル変換」してあることが前提です(していないと押せません)。\n影の濃さ以外(削除ボーンなど)を変えた場合は反映できないので「フル変換」を押してください", "Rebuilds the MOD changing only shadow strength (about 1 minute; Full Convert takes about 6 minutes).\nRequires that this avatar has already been through \"Full Convert\" once (otherwise this button is disabled).\nIf you changed anything other than shadow strength (e.g. drop bones), use \"Full Convert\" instead.", "그림자 농도만 변경하여 모드를 다시 만듭니다(약 1분. 전체 변환은 약 6분).\n이 아바타를 한 번 「전체 변환」한 것이 전제입니다(하지 않았으면 누를 수 없습니다).\n그림자 농도 이외(삭제 본 등)를 변경한 경우에는 반영되지 않으므로 「전체 변환」을 눌러주세요", "僅變更陰影濃度並重新建立 MOD(約 1 分鐘。完整轉換約需 6 分鐘)。\n前提是這個角色模型已經執行過一次「完整轉換」(未執行過則無法按下此按鈕)。\n若變更了陰影濃度以外的設定(如刪除骨骼等),請改按「完整轉換」", "仅更改阴影浓度并重新生成 MOD(约 1 分钟。完整转换约需 6 分钟)。\n前提是该角色模型已执行过一次「完整转换」(未执行则无法点击此按钮)。\n如果更改了阴影浓度以外的设置(如删除骨骼等),请改为点击「完整转换」" } },
            { "LabelDropBones", new[] { "削除ボーン(上級):", "Drop Bones (Advanced):", "삭제할 본(고급):", "刪除骨骼(進階):", "删除骨骼(高级):" } },
            { "TipDropBones", new[] { "カンマ区切りでボーン名を指定すると、そのボーン(と子孫)に付いたパーツを削除します。\nボーン名の一覧はプレビュー生成後の work\\<名前>\\converted\\avatar_meta.json の \"bones\" を参照", "Enter bone names separated by commas to remove parts attached to those bones (and their descendants).\nSee the \"bones\" list in work\\<name>\\converted\\avatar_meta.json after a preview has been generated.", "쉼표로 구분하여 본 이름을 지정하면 해당 본(및 자식)에 붙은 파츠를 삭제합니다.\n본 이름 목록은 미리보기 생성 후 work\\<이름>\\converted\\avatar_meta.json의 \"bones\"를 참조하세요", "以逗號分隔輸入骨骼名稱,即可刪除附加在該骨骼(及其子代)上的部件。\n骨骼名稱清單請參閱產生預覽後的 work\\<名稱>\\converted\\avatar_meta.json 中的 \"bones\"", "以逗号分隔输入骨骼名称,即可删除附加在该骨骼(及其子级)上的部件。\n骨骼名称列表请参见生成预览后的 work\\<名称>\\converted\\avatar_meta.json 中的 \"bones\"" } },
            { "HintDropBonesEmpty", new[] { "(通常は空欄でOK)", "(usually fine to leave blank)", "(보통 비워둬도 됩니다)", "(通常留空即可)", "(通常留空即可)" } },
            { "BtnPreviewUpdate", new[] { "プレビュー更新", "Update Preview", "미리보기 업데이트", "更新預覽", "更新预览" } },
            { "TipPreviewButton", new[] { "プレビュー画像を再生成します(削除ボーン設定の反映)", "Regenerates the preview image (reflects drop bone settings)", "미리보기 이미지를 다시 생성합니다(삭제 본 설정 반영)", "重新產生預覽圖(套用刪除骨骼設定)", "重新生成预览图(应用删除骨骼设置)" } },
            { "LabelPakList", new[] { "作成済みMOD一覧:", "Created MODs:", "생성된 모드 목록:", "已建立的 MOD 清單:", "已创建的 MOD 列表:" } },
            { "AppliedStatusChecking", new[] { "適用中: (確認中)", "Applied: (checking...)", "적용 중: (확인 중)", "套用中: (確認中)", "应用中: (确认中)" } },
            { "AppliedStatusNoPaksDir", new[] { "適用中: (Paksフォルダ未設定)", "Applied: (Paks folder not set)", "적용 중: (Paks 폴더 미설정)", "套用中: (尚未設定 Paks 資料夾)", "应用中: (尚未设置 Paks 文件夹)" } },
            { "AppliedStatusNone", new[] { "適用中: なし(元のパルワールド)", "Applied: none (original Palworld)", "적용 중: 없음(원본 팰월드)", "套用中: 無(原版幻獸帕魯)", "应用中: 无(原版幻兽帕鲁)" } },
            { "AppliedStatusUnknownMod", new[] { "適用中: 内容不明のMODが入っています", "Applied: an unknown MOD is installed", "적용 중: 알 수 없는 모드가 설치되어 있습니다", "套用中: 已安裝內容不明的 MOD", "应用中: 已安装内容不明的 MOD" } },
            { "AppliedStatusCheckFailed", new[] { "適用中: (確認できませんでした)", "Applied: (could not verify)", "적용 중: (확인할 수 없었습니다)", "套用中: (無法確認)", "应用中: (无法确认)" } },
            { "AppliedStatusNamedFormat", new[] { "適用中: {0}", "Applied: {0}", "적용 중: {0}", "套用中: {0}", "应用中: {0}" } },
            { "ColAvatar", new[] { "アバター", "Avatar", "아바타", "角色模型", "角色模型" } },
            { "ColFile", new[] { "ファイル", "File", "파일", "檔案", "文件" } },
            { "ColSize", new[] { "サイズ", "Size", "크기", "大小", "大小" } },
            { "ColCreatedAt", new[] { "作成日時", "Created", "생성 일시", "建立時間", "创建时间" } },
            { "BtnApply", new[] { "Palworldに適用", "Apply to Palworld", "팰월드에 적용", "套用至幻獸帕魯", "应用到幻兽帕鲁" } },
            { "BtnRemoveMod", new[] { "MODを解除", "Remove MOD", "모드 해제", "解除 MOD", "解除 MOD" } },
            { "BtnRefreshList", new[] { "一覧を更新", "Refresh List", "목록 새로고침", "重新整理清單", "刷新列表" } },
            { "BtnDeleteResult", new[] { "変換結果を削除", "Delete Conversion Result", "변환 결과 삭제", "刪除轉換結果", "删除转换结果" } },
            { "BtnReport", new[] { "問合せ", "Contact", "문의하기", "問題回報", "问题反馈" } },
            { "TipApply", new[] { "選んだMODをPalworldへ入れます(同時に入るのは常に1体だけ)", "Installs the selected MOD into Palworld (only one can be installed at a time)", "선택한 모드를 팰월드에 설치합니다(동시에 하나만 적용 가능)", "將選取的 MOD 套用至幻獸帕魯(同一時間僅能套用一個)", "将选中的 MOD 应用到幻兽帕鲁(同一时间只能应用一个)" } },
            { "TipRemove", new[] { "MODを外して元のパルワールドに戻します", "Removes the MOD and restores the original Palworld", "모드를 제거하고 원본 팰월드로 되돌립니다", "移除 MOD 並還原成原版幻獸帕魯", "移除 MOD 并还原为原版幻兽帕鲁" } },
            { "TipDelete", new[] { "選んだアバターのMODファイルと変換用プロジェクトを削除してディスクを空けます", "Deletes the selected avatar's MOD file and conversion project to free disk space", "선택한 아바타의 모드 파일과 변환용 프로젝트를 삭제하여 디스크 공간을 확보합니다", "刪除選取角色模型的 MOD 檔案與轉換用專案,以釋放磁碟空間", "删除选中角色模型的 MOD 文件与转换用工程,以释放磁盘空间" } },
            { "TipReport", new[] { "不具合の報告・お問い合わせはこちら(診断ログを送信します)", "Report a problem or ask a question here (sends diagnostic logs)", "문제 신고나 문의는 여기서(진단 로그를 전송합니다)", "回報問題或洽詢請按此(將傳送診斷紀錄)", "反馈问题或咨询请点此(将发送诊断日志)" } },
            { "CheckAutoApply", new[] { "変換完了後に自動でPalworldへ適用", "Automatically apply to Palworld after conversion", "변환 완료 후 자동으로 팰월드에 적용", "轉換完成後自動套用至幻獸帕魯", "转换完成后自动应用到幻兽帕鲁" } },
            { "TipAutoApply", new[] { "変換が終わったら自動でPalworldに適用します", "Automatically applies to Palworld once conversion finishes", "변환이 끝나면 자동으로 팰월드에 적용합니다", "轉換結束後會自動套用至幻獸帕魯", "转换结束后会自动应用到幻兽帕鲁" } },
            { "TipUpdateLabel", new[] { "クリックすると入手先ページ(BOOTH)をブラウザで開きます", "Click to open the download page (BOOTH) in your browser", "클릭하면 다운로드 페이지(BOOTH)를 브라우저에서 엽니다", "點擊後會在瀏覽器開啟下載頁面(BOOTH)", "点击后会在浏览器中打开下载页面(BOOTH)" } },
            { "ConfirmExitWhileRunningBody", new[] { "変換が実行中です。中止して閉じますか?", "A conversion is running. Cancel it and close?", "변환이 실행 중입니다. 중지하고 닫으시겠습니까?", "轉換正在執行中。要中止並關閉嗎?", "转换正在进行中。要中止并关闭吗?" } },
            { "WhatAvatarLoad", new[] { "アバターの読み込み", "Avatar loading", "아바타 불러오기", "讀取角色模型", "读取角色模型" } },
            { "WhatScreenUpdate", new[] { "画面の更新", "Screen update", "화면 업데이트", "更新畫面", "更新画面" } },
            { "WhatPalworldVersionCheck", new[] { "パルワールドのバージョン確認", "Palworld version check", "팰월드 버전 확인", "確認幻獸帕魯版本", "确认幻兽帕鲁版本" } },
            { "WhatAppliedModCheck", new[] { "適用中のMODの確認", "Applied MOD check", "적용 중인 모드 확인", "確認目前套用的 MOD", "确认目前应用的 MOD" } },
            { "ErrFailedFormat", new[] { "{0}に失敗しました: {1}", "{0} failed: {1}", "{0}에 실패했습니다: {1}", "{0}失敗: {1}", "{0}失败: {1}" } },
            { "MsgDropVrmOrPrefab", new[] { ".vrm / .prefab ファイルをドロップしてください", "Please drop a .vrm or .prefab file", ".vrm / .prefab 파일을 놓아주세요", "請拖放 .vrm 或 .prefab 檔案", "请拖放 .vrm 或 .prefab 文件" } },
            // dev#236(2026-07-30): 「初回セットアップが必要です」Yes/No確認モーダル
            // (MsgBlenderSetupNeededBody/TitleBlenderSetupNeeded)と、その案内文が
            // 参照していた手動配置ヒント(HintBlenderManualSetup)はここに置いていたが、
            // モーダル自体を撤去したため削除した。手動配置の案内は
            // pipeline\cli\ensure_blender.ps1 の Show-D2PFailureGuidance が自動取得
            // 失敗時に出す(そちらは元々ローカライズ対象外の診断文で、常設statusLabelに
            // そのまま出る。差し替え不要)。
            { "MsgHumanoidJsonNeededBody", new[] { "FBXを使うには、ボーン対応表(humanoid.json)がFBXと同じフォルダに必要です。\n\n作り方:\n1. ツールの unity\\HumanoidMapExporter.cs を\n   Unityプロジェクトの Assets\\Editor\\ に入れる\n2. アバターを選択して メニュー Tools > DiveToPalworld >\n   Export Humanoid Map を実行\n3. 出てきた humanoid.json をFBXと同じフォルダに置く", "To use an FBX file, a bone mapping file (humanoid.json) is required in the same folder as the FBX.\n\nHow to create it:\n1. Put the tool's unity\\HumanoidMapExporter.cs into\n   Assets\\Editor\\ in your Unity project\n2. Select the avatar and run menu Tools > DiveToPalworld >\n   Export Humanoid Map\n3. Place the resulting humanoid.json in the same folder as the FBX", "FBX를 사용하려면 본 대응표(humanoid.json)가 FBX와 같은 폴더에 있어야 합니다.\n\n만드는 방법:\n1. 툴의 unity\\HumanoidMapExporter.cs를\n   Unity 프로젝트의 Assets\\Editor\\ 에 넣기\n2. 아바타를 선택하고 메뉴 Tools > DiveToPalworld >\n   Export Humanoid Map 실행\n3. 생성된 humanoid.json을 FBX와 같은 폴더에 배치", "若要使用 FBX,需要在與 FBX 相同的資料夾中放置骨骼對應表(humanoid.json)。\n\n製作方式:\n1. 將工具內的 unity\\HumanoidMapExporter.cs\n   放入 Unity 專案的 Assets\\Editor\\ 中\n2. 選取角色模型後執行選單 Tools > DiveToPalworld >\n   Export Humanoid Map\n3. 將產生的 humanoid.json 放到與 FBX 相同的資料夾", "若要使用 FBX,需要在与 FBX 相同的文件夹中放置骨骼对应表(humanoid.json)。\n\n制作方式:\n1. 将工具内的 unity\\HumanoidMapExporter.cs\n   放入 Unity 工程的 Assets\\Editor\\ 中\n2. 选中角色模型后执行菜单 Tools > DiveToPalworld >\n   Export Humanoid Map\n3. 将生成的 humanoid.json 放到与 FBX 相同的文件夹" } },
            { "TitleHumanoidJsonNeeded", new[] { "humanoid.json が必要です", "humanoid.json Required", "humanoid.json이 필요합니다", "需要 humanoid.json", "需要 humanoid.json" } },
            { "DlgDescPaksFolder", new[] { "PalworldのPaksフォルダを選んでください (<Palworld>\\Pal\\Content\\Paks)", "Select Palworld's Paks folder (<Palworld>\\Pal\\Content\\Paks)", "팰월드의 Paks 폴더를 선택하세요 (<Palworld>\\Pal\\Content\\Paks)", "請選擇幻獸帕魯的 Paks 資料夾 (<Palworld>\\Pal\\Content\\Paks)", "请选择幻兽帕鲁的 Paks 文件夹 (<Palworld>\\Pal\\Content\\Paks)" } },
            { "MsgPaksNotFoundFormat", new[] { "選んだフォルダに {0} が見つかりません:\n{1}\n\n正しい Paks フォルダ(<Palworld>\\Pal\\Content\\Paks)を選び直してください。", "{0} was not found in the selected folder:\n{1}\n\nPlease select the correct Paks folder (<Palworld>\\Pal\\Content\\Paks) again.", "선택한 폴더에서 {0}을(를) 찾을 수 없습니다:\n{1}\n\n올바른 Paks 폴더(<Palworld>\\Pal\\Content\\Paks)를 다시 선택해주세요.", "在選取的資料夾中找不到 {0}:\n{1}\n\n請重新選擇正確的 Paks 資料夾(<Palworld>\\Pal\\Content\\Paks)。", "在选中的文件夹中找不到 {0}:\n{1}\n\n请重新选择正确的 Paks 文件夹(<Palworld>\\Pal\\Content\\Paks)。" } },
            { "TitlePalworldNotFound", new[] { "Palworldが見つかりません", "Palworld Not Found", "팰월드를 찾을 수 없습니다", "找不到幻獸帕魯", "找不到幻兽帕鲁" } },
            { "TitlePalworldVersionCheck", new[] { "パルワールドのバージョン確認", "Palworld Version Check", "팰월드 버전 확인", "幻獸帕魯版本確認", "幻兽帕鲁版本确认" } },
            // dev#103(裁定2026-07-29「他MOD共存は一切対応しない/検出した時点でNG」): 起動時に
            // Paksフォルダへ自分以外の.pakを検出したら警告のみ表示(ブロックはしない)
            { "TitleOtherModsDetected", new[] { "他のMODを検出しました", "Other Mods Detected", "다른 모드를 감지했습니다", "偵測到其他 MOD", "检测到其他 MOD" } },
            { "MsgOtherModsDetectedFormat", new[] {
                "Paksフォルダに、このツール以外の.pakファイルが {0} 件見つかりました。\n\nUchinoko for Palworldは他のMODとの併用に対応していません。\n見た目が崩れる・MODが反映されない等の問題が起きることがあります。\n問題が起きた場合は他のMODを一旦外してからお試しください。",
                "Found {0} other .pak file(s) in the Paks folder besides this tool's own.\n\nUchinoko for Palworld does not support running alongside other mods.\nThis can cause broken appearance, the MOD not applying, and similar issues.\nIf you run into problems, please remove the other mods and try again.",
                "Paks 폴더에서 이 도구 외의 .pak 파일 {0}개를 발견했습니다.\n\nUchinoko for Palworld는 다른 모드와의 병용을 지원하지 않습니다.\n외형이 깨지거나 모드가 반영되지 않는 등의 문제가 발생할 수 있습니다.\n문제가 발생하면 다른 모드를 제거한 후 다시 시도해주세요.",
                "在 Paks 資料夾中發現除本工具外的 {0} 個 .pak 檔案。\n\nUchinoko for Palworld 不支援與其他 MOD 併用。\n可能發生外觀損壞、MOD 未套用等問題。\n若發生問題,請先移除其他 MOD 後再試一次。",
                "在 Paks 文件夹中发现除本工具外的 {0} 个 .pak 文件。\n\nUchinoko for Palworld 不支持与其他 MOD 并用。\n可能发生外观损坏、MOD 未生效等问题。\n若发生问题,请先移除其他 MOD 后再试一次。"
            } },
            { "MsgPalworldVersionMismatchFormat", new[] { "お使いのパルワールドは、このツールが動作確認したバージョンと異なります。\n  動作確認済み: {0}\n  お使いのもの: {1}\n\nそのまま使えることも多いですが、パルワールドの更新後は変換したMODが\nうまく動かない場合があります。おかしくなったら「MODを解除」してください。", "Your Palworld version differs from the ones this tool was verified against.\n  Verified: {0}\n  Yours: {1}\n\nIt often still works, but after a Palworld update the converted MOD\nmay not work correctly. If something looks wrong, use \"Remove MOD\".", "사용 중인 팰월드가 이 도구가 동작 확인한 버전과 다릅니다.\n  동작 확인 완료: {0}\n  사용 중인 버전: {1}\n\n그대로 사용할 수 있는 경우도 많지만, 팰월드 업데이트 후에는 변환한 모드가\n제대로 작동하지 않을 수 있습니다. 이상이 있으면 「모드 해제」를 눌러주세요.", "您使用的幻獸帕魯版本,與本工具已驗證的版本不同。\n  已驗證: {0}\n  您使用的版本: {1}\n\n多數情況下仍可正常使用,但幻獸帕魯更新後,轉換出的 MOD\n可能無法正常運作。若出現異常,請按「解除 MOD」。", "您使用的幻兽帕鲁版本,与本工具已验证的版本不同。\n  已验证: {0}\n  您使用的版本: {1}\n\n多数情况下仍可正常使用,但幻兽帕鲁更新后,转换出的 MOD\n可能无法正常运作。若出现异常,请点击「解除 MOD」。" } },
            { "UpdateNoticeFormat", new[] { "新しいバージョン {0} があります(クリックで入手先を開く)", "A new version {0} is available (click to open the download page)", "새 버전 {0}이(가) 있습니다(클릭하면 다운로드 페이지가 열립니다)", "有新版本 {0}(點擊開啟下載頁面)", "有新版本 {0}(点击打开下载页面)" } },
            // dev#216 WP1(2026-07-30)で新設した当初は、このボタンがアプリ内で
            // ダウンロード・検証・展開まで行っていた。適用(ファイル入れ替え)を担う
            // ランチャー側の適用エンジンは2026-07-31のランチャー廃止で配布物から
            // 除去され、ダウンロードした内容を適用する者がいなくなった(実測で
            // 確認)。2026-07-31にダウンロード経路自体を削除し、updateLabelと
            // 同じくクリックで配布ページ(BOOTH等)を開くだけのボタンへ改めた
            // (CLAUDE.md「実装した」と「効いている」は別、を踏まえ、実際に起きることを
            // そのまま伝える文言にした)
            { "BtnUpdateNow", new[] { "最新版を入手", "Get Latest Version", "최신 버전 받기", "取得最新版本", "获取最新版本" } },
            { "TipUpdateNow", new[] {
                "最新版の入手先ページ(BOOTH等)をブラウザで開きます",
                "Opens the page (BOOTH, etc.) to get the latest version in your browser",
                "브라우저에서 최신 버전을 받을 수 있는 페이지(BOOTH 등)를 엽니다",
                "在瀏覽器中開啟取得最新版本的頁面(BOOTH 等)",
                "在浏览器中打开获取最新版本的页面(BOOTH 等)" } },
            { "CauseNoWritePermission", new[] { "書き込み権限がありません", "No write permission", "쓰기 권한이 없습니다", "沒有寫入權限", "没有写入权限" } },
            { "ActionNoWritePermission", new[] { "Palworldを終了してから再試行するか、Uchinoko.exeを右クリック→「管理者として実行」でお試しください", "Close Palworld and try again, or right-click Uchinoko.exe and choose \"Run as administrator\"", "팰월드를 종료한 후 다시 시도하거나, Uchinoko.exe를 우클릭하여 「관리자 권한으로 실행」을 시도해보세요", "請先關閉幻獸帕魯後再試一次,或在 Uchinoko.exe 上按右鍵選擇「以系統管理員身分執行」", "请先关闭幻兽帕鲁后再试一次,或在 Uchinoko.exe 上单击右键选择「以管理员身份运行」" } },
            { "CauseDiskFull", new[] { "ディスクの空き容量が不足しています", "Not enough free disk space", "디스크 여유 공간이 부족합니다", "磁碟可用空間不足", "磁盘可用空间不足" } },
            { "ActionDiskFull", new[] { "適用先ドライブの空き容量を確保してから再試行してください", "Free up space on the target drive and try again", "적용 대상 드라이브의 여유 공간을 확보한 후 다시 시도해주세요", "請先確保目標磁碟有足夠可用空間後再試一次", "请先确保目标磁盘有足够可用空间后再试一次" } },
            { "CauseFileInUse", new[] { "ファイルが他のプログラムに使われている可能性があります", "The file may be in use by another program", "파일이 다른 프로그램에서 사용 중일 수 있습니다", "檔案可能正被其他程式使用", "文件可能正被其他程序占用" } },
            { "ActionFileInUse", new[] { "Palworldやウイルス対策ソフトを終了/一時停止してから再試行してください", "Close Palworld or pause your antivirus software, then try again", "팰월드나 백신 프로그램을 종료/일시중지한 후 다시 시도해주세요", "請結束幻獸帕魯或暫停防毒軟體後再試一次", "请关闭幻兽帕鲁或暂停杀毒软件后再试一次" } },
            { "CauseTargetFolderNotFound", new[] { "適用先フォルダが見つかりません(Palworldの場所の設定が古い可能性)", "The target folder could not be found (the saved Palworld location may be outdated)", "적용 대상 폴더를 찾을 수 없습니다(팰월드 위치 설정이 오래되었을 수 있습니다)", "找不到目標資料夾(幻獸帕魯的位置設定可能已過期)", "找不到目标文件夹(幻兽帕鲁的位置设置可能已过期)" } },
            { "ActionTargetFolderNotFound", new[] { "「こだわり設定」でPaksフォルダの場所を設定し直してください", "Reset the Paks folder location in \"Advanced Settings\"", "「세부 설정」에서 Paks 폴더 위치를 다시 설정해주세요", "請在「進階設定」中重新設定 Paks 資料夾位置", "请在「高级设置」中重新设置 Paks 文件夹位置" } },
            { "CauseUnexpected", new[] { "予期しないエラーです", "An unexpected error occurred", "예기치 않은 오류입니다", "發生非預期的錯誤", "发生非预期的错误" } },
            { "ActionUnexpected", new[] { "「問合せ」ボタンから診断ログを送信してご連絡ください", "Please send us the diagnostic log via the \"Contact\" button", "「문의하기」 버튼으로 진단 로그를 보내주세요", "請透過「問題回報」按鈕傳送診斷紀錄與我們聯絡", "请通过「问题反馈」按钮发送诊断日志与我们联系" } },
            { "LabelApply", new[] { "適用", "Apply", "적용", "套用", "应用" } },
            { "LabelRemove", new[] { "解除", "Remove", "해제", "解除", "解除" } },
            { "MsgApplyFailureBodyFormat", new[] { "{0}に失敗しました。\n\n原因: {1}\n対処: {2}\n\n適用先: {3}\n詳しい内容は右のログ欄から確認できます。", "{0} failed.\n\nCause: {1}\nWhat to do: {2}\n\nTarget: {3}\nSee the log panel on the right for details.", "{0}에 실패했습니다.\n\n원인: {1}\n대처: {2}\n\n대상: {3}\n자세한 내용은 오른쪽 로그란에서 확인할 수 있습니다.", "{0}失敗。\n\n原因: {1}\n處理方式: {2}\n\n目標位置: {3}\n詳細內容請參閱右側的紀錄欄。", "{0}失败。\n\n原因: {1}\n处理方式: {2}\n\n目标位置: {3}\n详细内容请参见右侧的日志栏。" } },
            { "MsgApplyFailureTitleFormat", new[] { "{0}エラー", "{0} Error", "{0} 오류", "{0}錯誤", "{0}错误" } },
            { "MsgSelectModFromList", new[] { "一覧から適用するMODを選んでください", "Please select a MOD to apply from the list", "목록에서 적용할 모드를 선택해주세요", "請從清單中選擇要套用的 MOD", "请从列表中选择要应用的 MOD" } },
            { "MsgGameRunningApply", new[] { "パルワールドが起動中です。ゲームを終了してから適用してください。", "Palworld is currently running. Please close the game before applying.", "팰월드가 실행 중입니다. 게임을 종료한 후 적용해주세요.", "幻獸帕魯正在執行中。請先結束遊戲後再套用。", "幻兽帕鲁正在运行中。请先关闭游戏后再应用。" } },
            { "MsgModFileNotFoundFormat", new[] { "MODファイルが見つかりません: {0}", "MOD file not found: {0}", "모드 파일을 찾을 수 없습니다: {0}", "找不到 MOD 檔案: {0}", "找不到 MOD 文件: {0}" } },
            { "StatusAppliedFormat", new[] { "適用しました: {0}", "Applied: {0}", "적용했습니다: {0}", "已套用: {0}", "已应用: {0}" } },
            { "MsgApplySuccessFormat", new[] { "{0} を適用しました!\nゲームを起動して確認してください。", "{0} has been applied!\nStart the game to check the result.", "{0}을(를) 적용했습니다!\n게임을 실행하여 확인해주세요.", "已套用 {0}!\n請啟動遊戲確認結果。", "已应用 {0}!\n请启动游戏确认效果。" } },
            { "TitleApplySuccess", new[] { "適用完了", "Applied Successfully", "적용 완료", "套用完成", "应用完成" } },
            { "ConfirmDeleteHeaderFormat", new[] { "{0} について、このツールが作ったものをすべて削除しますか?", "Delete everything this tool created for {0}?", "{0}에 대해 이 도구가 만든 모든 것을 삭제하시겠습니까?", "是否要刪除本工具為 {0} 建立的所有內容?", "是否要删除本工具为 {0} 创建的所有内容?" } },
            { "LineModFileFormat", new[] { "・MODファイル: {0}", "- MOD file: {0}", "· 모드 파일: {0}", "‧MOD 檔案: {0}", "‧MOD 文件: {0}" } },
            { "LineWorkFolderFormat", new[] { "・設定・プレビュー等の作業フォルダ: {0}", "- Work folder (settings, previews, etc.): {0}", "· 설정·미리보기 등의 작업 폴더: {0}", "‧設定、預覽等工作資料夾: {0}", "‧设置、预览等工作文件夹: {0}" } },
            { "LineUeProjectFormat", new[] { "・変換用UEプロジェクト: {0}", "- Conversion UE project: {0}", "· 변환용 UE 프로젝트: {0}", "‧轉換用 UE 專案: {0}", "‧转换用 UE 工程: {0}" } },
            { "NoteVrmNotDeleted", new[] { "元のVRMファイルは削除されません。", "The original VRM file will not be deleted.", "원본 VRM 파일은 삭제되지 않습니다.", "原始的 VRM 檔案不會被刪除。", "原始的 VRM 文件不会被删除。" } },
            { "NoteReloadVrmToRedo", new[] { "また使う時はVRMを入れ直して最初からやり直しです。", "To use it again, you'll need to re-add the VRM and start over.", "다시 사용할 때는 VRM을 다시 넣고 처음부터 다시 진행해야 합니다.", "若之後要再次使用,需要重新放入 VRM 並從頭開始。", "若之后要再次使用,需要重新放入 VRM 并从头开始。" } },
            { "TitleConfirmDelete", new[] { "削除の確認", "Confirm Deletion", "삭제 확인", "確認刪除", "确认删除" } },
            { "MsgDeleteFailedFormat", new[] { "削除に失敗しました:\n{0}\n(変換が実行中でないか、エクスプローラ等で開いていないか確認してください)", "Deletion failed:\n{0}\n(Check that a conversion isn't running and that the folder isn't open in Explorer or elsewhere)", "삭제에 실패했습니다:\n{0}\n(변환이 실행 중이지 않은지, 탐색기 등에서 열려 있지 않은지 확인해주세요)", "刪除失敗:\n{0}\n(請確認轉換是否正在執行,或該資料夾是否在檔案總管等程式中開啟)", "删除失败:\n{0}\n(请确认转换是否正在进行,或该文件夹是否在资源管理器等程序中打开)" } },
            { "StatusDeletedFormat", new[] { "{0} の生成物をすべて削除しました", "All generated files for {0} have been deleted", "{0}의 생성물을 모두 삭제했습니다", "已刪除 {0} 的所有產生內容", "已删除 {0} 的所有生成内容" } },
            { "SupportStage1Info", new[] { "下のボタンを押すと問合せフォームを開きます。そのさい、ログが送信されます。\nログの送信に際して、利用者は開発者(大崎商会)に全面的な利用権を\n委託したものとします。", "Pressing the button below opens the contact form; your log will be sent at that time.\nBy sending the log, you grant the developer (Osaki Shokai) full rights to use it.", "아래 버튼을 누르면 문의 양식이 열립니다. 이때 로그가 전송됩니다.\n로그 전송 시, 이용자는 개발자(오사키상회)에게 로그의 전면적인\n이용 권한을 위임한 것으로 간주합니다.", "按下方按鈕即會開啟問題回報表單,此時將會傳送紀錄。\n傳送紀錄時,視同使用者已將該紀錄的完整使用權\n委託給開發者(大崎商會)。", "点击下方按钮即会打开问题反馈表单,此时将会发送日志。\n发送日志时,视同用户已将该日志的完整使用权\n委托给开发者(大崎商会)。" } },
            { "BtnOpenInquiryForm", new[] { "問い合わせフォームを開く", "Open Contact Form", "문의 양식 열기", "開啟問題回報表單", "打开问题反馈表单" } },
            { "BtnOk", new[] { "OK", "OK", "OK", "OK", "OK" } },
            { "SupportChangedNotice", new[] { "前回の報告以降にログが変わっています。再送してください。\n", "The log has changed since your last report. Please resend it.\n", "이전 보고 이후 로그가 변경되었습니다. 다시 전송해주세요.\n", "自上次回報後紀錄已有變動,請重新傳送。\n", "自上次反馈后日志已有变化,请重新发送。\n" } },
            { "SupportConfirmAppendBody", new[] { "次の内容が、前回と同じ問い合わせスレッドへ追記されます。よろしいですか?\n(問題のある内容があれば、編集してください)", "The following content will be added to the same inquiry thread as before. Continue?\n(Edit below if anything looks wrong.)", "다음 내용이 이전과 동일한 문의 스레드에 추가됩니다. 계속하시겠습니까?\n(문제가 있는 내용이 있으면 수정해주세요)", "以下內容將會附加到與上次相同的問題回報串。是否繼續?\n(如有不便公開的內容請自行編輯)", "以下内容将会附加到与上次相同的问题反馈串中。是否继续?\n(如有不便公开的内容请自行编辑)" } },
            { "SupportConfirmNewBody", new[] { "次の内容のログが送信されます。本当によろしいですか?\n(問題のある内容があれば、編集してください)", "The following log will be sent. Are you sure?\n(Edit below if anything looks wrong.)", "다음 내용의 로그가 전송됩니다. 정말 계속하시겠습니까?\n(문제가 있는 내용이 있으면 수정해주세요)", "將會傳送以下內容的紀錄。確定要繼續嗎?\n(如有不便公開的內容請自行編輯)", "将会发送以下内容的日志。确定要继续吗?\n(如有不便公开的内容请自行编辑)" } },
            { "SupportSendFailedUseManualCopy", new[] { "送信できませんでした。「ログを手動でコピー」をお使いください。", "Sending failed. Please use \"Copy Log Manually\" instead.", "전송하지 못했습니다. 「로그 수동 복사」를 이용해주세요.", "傳送失敗。請改用「手動複製紀錄」。", "发送失败。请改用「手动复制日志」。" } },
            { "SupportSending", new[] { "送信中...", "Sending...", "전송 중...", "傳送中...", "发送中..." } },
            { "SupportSendFailedOffline", new[] { "送信できませんでした(オフライン、または接続先の都合)。\n「ログを手動でコピー」もお使いいただけます。", "Sending failed (offline, or a problem with the server).\nYou can also use \"Copy Log Manually\".", "전송하지 못했습니다(오프라인이거나 서버 문제).\n「로그 수동 복사」도 이용하실 수 있습니다.", "傳送失敗(可能是離線或伺服器端問題)。\n您也可以使用「手動複製紀錄」。", "发送失败(可能是离线或服务器端问题)。\n您也可以使用「手动复制日志」。" } },
            { "SupportSentLabelFormat", new[] { "送信済みです(報告ID: {0})。\n対応状況・開発者からの返信は、下のページでいつでも確認できます:", "Already sent (Report ID: {0}).\nYou can check the status and any developer replies on the page below at any time:", "전송 완료(보고 ID: {0}).\n대응 현황과 개발자의 답변은 아래 페이지에서 언제든지 확인할 수 있습니다:", "已傳送(回報編號: {0})。\n處理進度與開發者的回覆,可隨時於下方頁面確認:", "已发送(反馈编号: {0})。\n处理进度与开发者的回复,可随时在下方页面查看:" } },
            { "BtnOpenSamePlace", new[] { "同じ場所を開く", "Open Same Page", "같은 페이지 열기", "開啟相同頁面", "打开相同页面" } },
            { "BtnResendLog", new[] { "ログを再送", "Resend Log", "로그 다시 전송", "重新傳送紀錄", "重新发送日志" } },
            { "BtnCopyLogManually", new[] { "ログを手動でコピー", "Copy Log Manually", "로그 수동 복사", "手動複製紀錄", "手动复制日志" } },
            { "BtnClose", new[] { "閉じる", "Close", "닫기", "關閉", "关闭" } },
            { "MsgLogCopiedBody", new[] { "ログをコピーしました。\n必要な場所に貼り付けてください。\n\nログにはファイルパスなど個人情報が含まれていることがあります。送付・公開前によく確認してください", "The log has been copied.\nPaste it wherever needed.\n\nThe log may contain personal information such as file paths. Please review it carefully before sending or posting it publicly.", "로그를 복사했습니다.\n필요한 곳에 붙여넣어 주세요.\n\n로그에는 파일 경로 등 개인정보가 포함될 수 있습니다. 전송·공개 전에 잘 확인해주세요", "已複製紀錄。\n請貼到需要的地方。\n\n紀錄中可能包含檔案路徑等個人資訊。傳送或公開前請務必仔細確認", "已复制日志。\n请粘贴到需要的地方。\n\n日志中可能包含文件路径等个人信息。发送或公开前请务必仔细确认" } },
            { "TitleLogCopied", new[] { "ログをコピー", "Log Copied", "로그 복사", "複製紀錄", "复制日志" } },
            { "MsgCopyFailedFormat", new[] { "コピーに失敗しました: {0}", "Copy failed: {0}", "복사에 실패했습니다: {0}", "複製失敗: {0}", "复制失败: {0}" } },
            { "MsgGameRunningRemove", new[] { "パルワールドが起動中です。ゲームを終了してから解除してください。", "Palworld is currently running. Please close the game before removing it.", "팰월드가 실행 중입니다. 게임을 종료한 후 해제해주세요.", "幻獸帕魯正在執行中。請先結束遊戲後再解除。", "幻兽帕鲁正在运行中。请先关闭游戏后再解除。" } },
            { "StatusNoModApplied", new[] { "MODは入っていません(すでに元の状態)", "No MOD is applied (already in original state)", "모드가 설치되어 있지 않습니다(이미 원본 상태)", "未套用任何 MOD(已是原始狀態)", "未应用任何 MOD(已是原始状态)" } },
            { "StatusModRemoved", new[] { "MODを解除しました(元のパルワールドに戻りました)", "MOD removed (restored to original Palworld)", "모드를 해제했습니다(원본 팰월드로 되돌아갔습니다)", "已解除 MOD(已還原成原版幻獸帕魯)", "已解除 MOD(已还原为原版幻兽帕鲁)" } },
            { "MsgAlreadyRunning", new[] { "実行中です", "Already running", "실행 중입니다", "執行中", "正在运行" } },
            { "MsgSpecifyVrmFile", new[] { "VRMファイルを指定してください", "Please specify a VRM file", "VRM 파일을 지정해주세요", "請指定 VRM 檔案", "请指定 VRM 文件" } },
            { "StatusPreviewGenerating", new[] { "プレビュー生成中...", "Generating preview...", "미리보기 생성 중...", "產生預覽中...", "生成预览中..." } },
            { "StatusMaterialsApplying", new[] { "影の濃さを反映中(1分ほど)...", "Applying shadow strength (about 1 minute)...", "그림자 농도 적용 중(약 1분)...", "套用陰影濃度中(約 1 分鐘)...", "应用阴影浓度中(约 1 分钟)..." } },
            { "StatusFullConverting", new[] { "フル変換中(時間がかかります)...", "Full conversion in progress (this takes a while)...", "전체 변환 중(시간이 걸립니다)...", "完整轉換中(需要一些時間)...", "完整转换中(需要一些时间)..." } },
            { "MsgOtherProcessRunning", new[] { "他の処理を実行中です。完了してからもう一度お試しください。", "Another process is running. Please try again once it finishes.", "다른 작업이 실행 중입니다. 완료 후 다시 시도해주세요.", "有其他作業正在執行中。請等待完成後再試一次。", "有其他操作正在进行中。请等待完成后再试一次。" } },
            { "MsgSpecifyPrefabFile", new[] { ".prefab ファイルを指定してください", "Please specify a .prefab file", ".prefab 파일을 지정해주세요", "請指定 .prefab 檔案", "请指定 .prefab 文件" } },
            { "MsgExportScriptNotFoundFormat", new[] { "エクスポートスクリプトが見つかりません:\n{0}", "Export script not found:\n{0}", "내보내기 스크립트를 찾을 수 없습니다:\n{0}", "找不到匯出腳本:\n{0}", "找不到导出脚本:\n{0}" } },
            { "StatusUnityExporting", new[] { "Unityプロジェクトからエクスポート中(数十秒〜。初回はパッケージ導入で数分かかることがあります)...", "Exporting from the Unity project (tens of seconds or more; the first time may take a few minutes for package setup)...", "Unity 프로젝트에서 내보내는 중(수십 초~. 처음에는 패키지 설치로 몇 분 걸릴 수 있습니다)...", "正在從 Unity 專案匯出中(數十秒以上;首次執行可能因套件安裝需數分鐘)...", "正在从 Unity 工程导出中(数十秒以上;首次执行可能因包安装需数分钟)..." } },
            { "StatusUnityExportFailed", new[] { "Unityエクスポートに失敗しました(右のログ参照)", "Unity export failed (see the log on the right)", "Unity 내보내기에 실패했습니다(오른쪽 로그 참조)", "Unity 匯出失敗(請參閱右側紀錄)", "Unity 导出失败(请参见右侧日志)" } },
            { "MsgUnityExportErrorBody", new[] { "Unityプロジェクトからのエクスポートに失敗しました。\n\nよくある原因:\n・指定したのがAssets配下のprefabではない\n・そのUnityプロジェクトが今Unity Editorで開かれている\n  (Unity Editorを閉じてからもう一度お試しください)\n・プロジェクトに合うバージョンのUnity Editorが見つからない\n\n詳しい内容は右のログ欄から確認できます。\n解決しない場合は、Unityのメニュー Tools > DiveToPalworld > Export Avatar で\n手動エクスポートし、出てきたFBXをこの画面へD&Dしてください。", "Export from the Unity project failed.\n\nCommon causes:\n- The file specified is not a prefab under Assets\n- The Unity project is currently open in Unity Editor\n  (close Unity Editor and try again)\n- No matching version of Unity Editor could be found for the project\n\nSee the log panel on the right for details.\nIf the problem persists, use the Unity menu Tools > DiveToPalworld > Export Avatar to\nexport manually, then drag & drop the resulting FBX onto this window.", "Unity 프로젝트에서 내보내기에 실패했습니다.\n\n일반적인 원인:\n· 지정한 것이 Assets 아래의 prefab이 아님\n· 해당 Unity 프로젝트가 현재 Unity Editor에서 열려 있음\n  (Unity Editor를 닫은 후 다시 시도해주세요)\n· 프로젝트에 맞는 버전의 Unity Editor를 찾을 수 없음\n\n자세한 내용은 오른쪽 로그란에서 확인할 수 있습니다.\n해결되지 않으면 Unity 메뉴 Tools > DiveToPalworld > Export Avatar에서\n수동으로 내보낸 후, 생성된 FBX를 이 화면으로 드래그 앤 드롭 해주세요.", "從 Unity 專案匯出失敗。\n\n常見原因:\n‧指定的檔案並非 Assets 底下的 prefab\n‧該 Unity 專案目前正在 Unity Editor 中開啟\n  (請先關閉 Unity Editor 後再試一次)\n‧找不到符合該專案的 Unity Editor 版本\n\n詳細內容請參閱右側的紀錄欄。\n若問題持續發生,請透過 Unity 選單 Tools > DiveToPalworld > Export Avatar\n手動匯出,再將產生的 FBX 拖放到此畫面。", "从 Unity 工程导出失败。\n\n常见原因:\n‧指定的文件并非 Assets 下的 prefab\n‧该 Unity 工程目前正在 Unity Editor 中打开\n  (请先关闭 Unity Editor 后再试一次)\n‧找不到符合该工程的 Unity Editor 版本\n\n详细内容请参见右侧的日志栏。\n若问题持续存在,请通过 Unity 菜单 Tools > DiveToPalworld > Export Avatar\n手动导出,再将生成的 FBX 拖放到此界面。" } },
            { "TitleUnityExportError", new[] { "Unityエクスポートエラー", "Unity Export Error", "Unity 내보내기 오류", "Unity 匯出錯誤", "Unity 导出错误" } },
            { "StatusUnityExportNoFbx", new[] { "エクスポートは完了しましたがFBXが見つかりませんでした", "Export finished but no FBX file was found", "내보내기는 완료되었지만 FBX 파일을 찾을 수 없습니다", "匯出已完成,但找不到 FBX 檔案", "导出已完成,但找不到 FBX 文件" } },
            { "MsgUnityExportNoFbxFormat", new[] { "Unityからのエクスポートは完了しましたが、出力フォルダにFBXが見つかりませんでした:\n{0}", "Export from Unity finished, but no FBX file was found in the output folder:\n{0}", "Unity에서의 내보내기는 완료되었지만, 출력 폴더에서 FBX 파일을 찾을 수 없습니다:\n{0}", "已從 Unity 完成匯出,但在輸出資料夾中找不到 FBX 檔案:\n{0}", "已从 Unity 完成导出,但在输出文件夹中找不到 FBX 文件:\n{0}" } },
            { "TitleUnityExport", new[] { "Unityエクスポート", "Unity Export", "Unity 내보내기", "Unity 匯出", "Unity 导出" } },
            { "StatusUnityExportDone", new[] { "Unityエクスポートが完了しました。アバターを取り込みます...", "Unity export finished. Loading the avatar...", "Unity 내보내기가 완료되었습니다. 아바타를 불러오는 중...", "Unity 匯出已完成,正在載入角色模型...", "Unity 导出已完成,正在加载角色模型..." } },
            { "StatusFailedOrCancelled", new[] { "失敗または中止されました(右のログ参照)", "Failed or cancelled (see the log on the right)", "실패했거나 중지되었습니다(오른쪽 로그 참조)", "已失敗或已中止(請參閱右側紀錄)", "已失败或已中止(请参见右侧日志)" } },
            { "MsgConvertDoneWithWarningsFormat", new[] { "変換は完了しましたが、注意事項があります:\n\n{0}", "Conversion finished, but there are some notes:\n\n{0}", "변환은 완료되었지만, 주의 사항이 있습니다:\n\n{0}", "轉換已完成,但有以下注意事項:\n\n{0}", "转换已完成,但有以下注意事项:\n\n{0}" } },
            { "TitleConvertDoneWithWarnings", new[] { "変換完了(注意事項あり)", "Conversion Complete (with Notes)", "변환 완료(주의 사항 있음)", "轉換完成(有注意事項)", "转换完成(有注意事项)" } },
            { "StatusPreviewDone", new[] { "プレビュー更新完了。フル変換できます", "Preview updated. Ready for full conversion", "미리보기 업데이트 완료. 전체 변환이 가능합니다", "預覽更新完成,可以進行完整轉換", "预览更新完成,可以进行完整转换" } },
            { "MsgPreviewDoneBody", new[] { "プレビューを更新しました。\n見た目(特に腕まわり)を確認して、問題なければ「フル変換」へ進んでください。", "The preview has been updated.\nCheck the appearance (especially around the arms), and if it looks fine, proceed to \"Full Convert\".", "미리보기를 업데이트했습니다.\n외형(특히 팔 주변)을 확인하고, 문제가 없으면 「전체 변환」으로 진행해주세요.", "已更新預覽。\n請確認外觀(尤其是手臂周圍),若沒問題請繼續進行「完整轉換」。", "已更新预览。\n请确认外观(尤其是手臂周围),若没问题请继续进行「完整转换」。" } },
            { "TitlePreviewDone", new[] { "プレビュー完了", "Preview Complete", "미리보기 완료", "預覽完成", "预览完成" } },
            { "StatusConvertDone", new[] { "変換完了!", "Conversion complete!", "변환 완료!", "轉換完成!", "转换完成!" } },
            { "MsgConvertDoneBody", new[] { "MODが完成しました!\n\n【使用方法】\nPalworldを起動していたら、閉じてください。\n「作成済みMOD一覧」から選んで「Palworldに適用」を押して下さい。\n\n【解除方法】\n「MODを解除」を押して下さい。", "The MOD is complete!\n\n[How to use]\nIf Palworld is running, please close it.\nSelect it from \"Created MODs\" and press \"Apply to Palworld\".\n\n[How to remove]\nPress \"Remove MOD\".", "모드가 완성되었습니다!\n\n【사용 방법】\n팰월드가 실행 중이라면 종료해주세요.\n「생성된 모드 목록」에서 선택하고 「팰월드에 적용」을 눌러주세요.\n\n【해제 방법】\n「모드 해제」를 눌러주세요.", "MOD 已完成!\n\n【使用方法】\n若幻獸帕魯正在執行,請先關閉。\n從「已建立的 MOD 清單」中選擇後按下「套用至幻獸帕魯」。\n\n【解除方法】\n請按下「解除 MOD」。", "MOD 已完成!\n\n【使用方法】\n若幻兽帕鲁正在运行,请先关闭。\n从「已创建的 MOD 列表」中选择后点击「应用到幻兽帕鲁」。\n\n【解除方法】\n请点击「解除 MOD」。" } },
            { "TitleConvertDone", new[] { "変換完了", "Conversion Complete", "변환 완료", "轉換完成", "转换完成" } },
            { "StatusAvatarLoading", new[] { "アバターを読み込み中...", "Loading avatar...", "아바타 불러오는 중...", "正在載入角色模型...", "正在加载角色模型..." } },
            { "StatusPromptVrmDnd", new[] { "VRMファイルを入れてください(D&DでOK)", "Please add a VRM file (drag & drop OK)", "VRM 파일을 넣어주세요(드래그 앤 드롭 가능)", "請放入 VRM 檔案(可拖放)", "请放入 VRM 文件(可拖放)" } },
            { "StatusPreviewStale", new[] { "プレビューが古い状態です。「プレビュー更新」を押すか、VRMを入れ直してください(反映後にフル変換が押せます)", "The preview is out of date. Press \"Update Preview\" or re-add the VRM (Full Convert will be enabled once updated)", "미리보기가 오래된 상태입니다. 「미리보기 업데이트」를 누르거나 VRM을 다시 넣어주세요(반영 후 전체 변환이 가능합니다)", "預覽已過期。請按「更新預覽」或重新放入 VRM(套用後即可進行完整轉換)", "预览已过期。请点击「更新预览」或重新放入 VRM(应用后即可进行完整转换)" } },
            { "StatusReadyToConvert", new[] { "フル変換できます", "Ready for full conversion", "전체 변환이 가능합니다", "可以進行完整轉換", "可以进行完整转换" } },
            { "StatusBlenderSetupNeeded", new[] { "Blenderのセットアップが必要です(「Blenderを再取得」を押してください)", "Blender setup is required (press \"Retry Blender Setup\")", "Blender 설정이 필요합니다(「Blender 다시 받기」를 눌러주세요)", "需要設定 Blender(請按「重新取得 Blender」)", "需要设置 Blender(请点击「重新获取 Blender」)" } },
            { "HintNeedFullConvertFirst", new[] { "(先に「フル変換」が必要です)", "(requires \"Full Convert\" first)", "(먼저 「전체 변환」이 필요합니다)", "(需先執行「完整轉換」)", "(需先执行「完整转换」)" } },
            { "MsgLicenseConfirmBody", new[] { "このアバターの利用規約は確認しましたか?\n\n・改変してよいこと\n・ゲーム内(MOD)で使用してよいこと\n\n確認と遵守は利用者の責任です。確認済みなら「はい」を押してください。\n(このアバターについて次回からは聞きません)\n\n---\n\nまた、Palworld側の利用条件についてもご確認ください。\n\n本ツールはシングルプレイ専用のクライアント側MODです。\nPalworldの規約はファイル改変を禁じる条項を含みますが、\n開発元は公式にMODを歓迎しており、\n明確な禁止はマルチプレイでの使用のみです。\nマルチプレイでは使用せず、セーブデータのバックアップを取った上で、\n自己責任でご利用ください。\n\n上記すべてに同意し、確認済みなら「はい」を押してください。", "Have you checked this avatar's terms of use?\n\n- That modification is allowed\n- That in-game (MOD) use is allowed\n\nChecking and complying with them is the user's responsibility. If you have confirmed this, press \"Yes\".\n(You won't be asked again for this avatar.)\n\n---\n\nPlease also check Palworld's own terms of use.\n\nThis tool is a single-player-only client-side MOD.\nPalworld's terms include a clause prohibiting file modification,\nbut the developer officially welcomes MODs;\nthe only explicit prohibition is use in multiplayer.\nDo not use it in multiplayer, back up your save data,\nand use it at your own risk.\n\nIf you agree to all of the above and have confirmed it, press \"Yes\".", "이 아바타의 이용약관을 확인하셨습니까?\n\n· 개조해도 되는지\n· 게임 내(모드)에서 사용해도 되는지\n\n확인과 준수는 이용자의 책임입니다. 확인했다면 「예」를 눌러주세요.\n(이 아바타에 대해서는 다음부터 묻지 않습니다)\n\n---\n\n또한 팰월드 측의 이용 조건도 확인해주세요.\n\n본 도구는 싱글 플레이 전용 클라이언트 측 모드입니다.\n팰월드의 약관에는 파일 개조를 금지하는 조항이 있지만,\n개발사는 공식적으로 모드를 환영하고 있으며,\n명확히 금지하는 것은 멀티플레이에서의 사용뿐입니다.\n멀티플레이에서는 사용하지 말고, 세이브 데이터를 백업한 후\n자기 책임 하에 이용해주세요.\n\n위 사항 모두에 동의하고 확인했다면 「예」를 눌러주세요.", "您是否已確認過這個角色模型的使用條款?\n\n‧是否允許進行改造\n‧是否允許在遊戲內(MOD)使用\n\n確認與遵守是使用者的責任。若已確認,請按「是」。\n(關於這個角色模型,下次將不會再次詢問)\n\n---\n\n此外,也請確認幻獸帕魯本身的使用條件。\n\n本工具是僅限單人遊玩的客戶端 MOD。\n幻獸帕魯的條款雖包含禁止修改檔案的條文,\n但開發商官方表示歡迎 MOD,\n明確禁止的僅限於多人遊戲中的使用。\n請勿在多人遊戲中使用,並在備份存檔資料後,\n自行承擔風險使用。\n\n若同意以上所有內容且已確認,請按「是」。", "您是否已确认过这个角色模型的使用条款?\n\n‧是否允许进行改造\n‧是否允许在游戏内(MOD)使用\n\n确认与遵守是用户的责任。若已确认,请点击「是」。\n(关于这个角色模型,下次将不再询问)\n\n---\n\n此外,也请确认幻兽帕鲁本身的使用条件。\n\n本工具是仅限单人游玩的客户端 MOD。\n幻兽帕鲁的条款虽包含禁止修改文件的条文,\n但开发商官方表示欢迎 MOD,\n明确禁止的仅限于多人游戏中的使用。\n请勿在多人游戏中使用,并在备份存档数据后,\n自行承担风险使用。\n\n若同意以上所有内容且已确认,请点击「是」。" } },
            { "TitleLicenseConfirm", new[] { "利用規約・使用条件の確認", "Confirm Terms of Use", "이용약관·사용 조건 확인", "確認使用條款與條件", "确认使用条款与条件" } },
            { "ErrBlenderSetupStartFailedFormat", new[] { "Blenderセットアップの起動に失敗しました: {0}", "Failed to start Blender setup: {0}", "Blender 설정 시작에 실패했습니다: {0}", "啟動 Blender 設定失敗: {0}", "启动 Blender 设置失败: {0}" } },
            { "MsgBlenderNotFoundDevFormat", new[] { "Blenderが見つかりません({0})。開発環境の場合は tools\\ の配置を確認してください。", "Blender was not found ({0}). If this is a development environment, check the layout under tools\\.", "Blender를 찾을 수 없습니다({0}). 개발 환경인 경우 tools\\ 배치를 확인해주세요.", "找不到 Blender({0})。若為開發環境,請確認 tools\\ 目錄的配置。", "找不到 Blender({0})。若为开发环境,请确认 tools\\ 目录的配置。" } },
            // dev#236: 旧「セットアップがキャンセルされました」(モーダルのキャンセル
            // ボタン専用文言)から、キャンセルUI廃止に伴い一般化した「失敗しました」へ改称
            { "MsgBlenderSetupFailedShort", new[] { "Blenderのセットアップに失敗しました(「Blenderを再取得」を押すとやり直せます)", "Blender setup failed (press \"Retry Blender Setup\" to try again)", "Blender 설정에 실패했습니다(「Blender 다시 받기」를 누르면 다시 시도할 수 있습니다)", "Blender 設定失敗(按「重新取得 Blender」可再試一次)", "Blender 设置失败(点击「重新获取 Blender」可再试一次)" } },
            // dev#236: 起動時バックグラウンドチェック中(通常は一瞬)に出す控えめな文言
            { "StatusBlenderChecking", new[] { "Blenderの状態を確認しています…", "Checking Blender setup...", "Blender 상태를 확인하고 있습니다…", "正在確認 Blender 狀態…", "正在确认 Blender 状态…" } },
            // dev#236: フル取得(ダウンロード+パッチ)進行中の進捗表示。{0}=工程名 {1}=進捗%
            { "StatusBlenderSettingUpFormat", new[] { "Blenderを準備中: {0} ({1}%)", "Setting up Blender: {0} ({1}%)", "Blender 준비 중: {0} ({1}%)", "正在準備 Blender: {0} ({1}%)", "正在准备 Blender: {0} ({1}%)" } },
            // dev#236: RunBackground()のwhat引数(失敗時ログの「〜に失敗しました」に使う)
            { "WhatBlenderSetup", new[] { "Blenderのセットアップ", "Blender setup", "Blender 설정", "Blender 設定", "Blender 设置" } },
            // dev#134(rd_125第14案 → 2026-07-29ぱん裁定でボタン案を却下、自動診断案へ転換):
            // 「インストール/作業先パスの健全性」(非ASCII/UNC/OneDrive配下/パス長。
            // convert.ps1のGet-PathFactsと同じ観点)を起動時に自動チェックし、リスクが
            // あれば具体的な次アクション付きで警告する。他の診断要素(Blender検出=
            // EnsureBlenderReadyOnStartup、Palworld版判定=CheckPalworldVersionOnce、
            // 他MOD検出=CheckOtherModsOnce)は既に同じ「起動時自動+ログに残る+必要なら
            // 警告」を満たしているため重複させない(PathHealthCheckOnStartup参照)。
            // 原因/対処の提示は既存のCause/Actionペア方式(ShowApplyFailure/
            // MsgApplyFailureBodyFormatと同じ型、実質dev#138が求める方向性そのもの)を
            // そのまま踏襲する。
            { "TitlePathHealthWarning", new[] { "環境チェック: 注意", "Environment Check: Warning", "환경 점검: 주의", "環境檢查: 注意", "环境检查: 注意" } },
            { "MsgPathHealthRiskFormat", new[] {
                "インストール先または作業先のフォルダに、変換が失敗しやすくなる要因が見つかりました。\n\n{0}\n\n詳細(サポートへの問い合わせ時にも記録されます):\n{1}",
                "Found factor(s) in the install or work folder that can make conversion more likely to fail.\n\n{0}\n\nDetails (also recorded when contacting support):\n{1}",
                "설치 위치 또는 작업 폴더에서 변환이 실패하기 쉬워지는 요인을 발견했습니다.\n\n{0}\n\n상세 내용(문의 시에도 기록됩니다):\n{1}",
                "在安裝位置或工作資料夾中,發現可能導致轉換容易失敗的因素。\n\n{0}\n\n詳細內容(問題回報時也會一併記錄):\n{1}",
                "在安装位置或工作文件夹中,发现可能导致转换容易失败的因素。\n\n{0}\n\n详细内容(问题反馈时也会一并记录):\n{1}"
            } },
            { "CausePathTooLong", new[] { "インストール先または作業先のパスが長すぎます(Windowsの制限に近づいています)", "The install or work location's path is too long (close to Windows' path length limit)", "설치 위치 또는 작업 위치의 경로가 너무 깁니다(Windows 제한에 근접)", "安裝位置或工作資料夾的路徑過長(接近 Windows 的限制)", "安装位置或工作文件夹的路径过长(接近 Windows 的限制)" } },
            { "ActionPathTooLong", new[] { "より短いパス(例: C:\\Uchinoko)へ移動してください", "Move it to a shorter path (e.g. C:\\Uchinoko)", "더 짧은 경로(예: C:\\Uchinoko)로 이동해주세요", "請移動到較短的路徑(例如 C:\\Uchinoko)", "请移动到较短的路径(例如 C:\\Uchinoko)" } },
            { "CausePathUnc", new[] { "インストール先または作業先がネットワークパス(UNC)です", "The install or work location is a network (UNC) path", "설치 위치 또는 작업 위치가 네트워크 경로(UNC)입니다", "安裝位置或工作資料夾為網路路徑(UNC)", "安装位置或工作文件夹为网络路径(UNC)" } },
            { "ActionPathUnc", new[] { "ローカルドライブへコピーしてから使ってください", "Copy it to a local drive before using it", "로컬 드라이브로 복사한 후 사용해주세요", "請先複製到本機磁碟後再使用", "请先复制到本机磁盘后再使用" } },
            { "CausePathOneDrive", new[] { "インストール先または作業先がOneDriveの同期フォルダ内です", "The install or work location is inside a OneDrive-synced folder", "설치 위치 또는 작업 위치가 OneDrive 동기화 폴더 안에 있습니다", "安裝位置或工作資料夾位於 OneDrive 同步資料夾內", "安装位置或工作文件夹位于 OneDrive 同步文件夹内" } },
            { "ActionPathOneDrive", new[] { "OneDriveの同期を一時停止するか、OneDrive外へ移動してください", "Pause OneDrive sync, or move it outside the OneDrive folder", "OneDrive 동기화를 일시중지하거나 OneDrive 밖으로 이동해주세요", "請暫停 OneDrive 同步,或移動到 OneDrive 資料夾外", "请暂停 OneDrive 同步,或移动到 OneDrive 文件夹外" } },
            // dev#298: 実報告R7GJY5W3(C:\Program Files\配下インストールで作業フォルダの
            // 作成がUnauthorizedAccessExceptionで失敗)。通常はappRoot\workが書き込めない場合
            // %LOCALAPPDATA%\Uchinoko\workへ自動フォールバックするため無言で解決するが、
            // そちらも書き込めない(稀。プロファイル破損等)場合だけこのエラーを出す。
            { "TitleWorkRootUnwritable", new[] { "作業フォルダを作成できません", "Cannot create a work folder", "작업 폴더를 만들 수 없습니다", "無法建立工作資料夾", "无法创建工作文件夹" } },
            { "MsgWorkRootUnwritableFormat", new[] {
                "作業用フォルダをどこにも作成できませんでした。\n\n試した場所:\n・{0}\n・{1}\n\nどちらも書き込み権限がないようです。管理者権限が必要な場所(C:\\Program Files 等)にインストールされている場合は、C:\\Uchinoko のような書き込み可能な場所へ移動して再度お試しください。",
                "Could not create a work folder anywhere.\n\nLocations tried:\n- {0}\n- {1}\n\nNeither location appears to be writable. If installed under a location that requires administrator rights (e.g. C:\\Program Files), please move it to a writable location such as C:\\Uchinoko and try again.",
                "작업 폴더를 어디에도 만들 수 없었습니다.\n\n시도한 위치:\n· {0}\n· {1}\n\n두 위치 모두 쓰기 권한이 없는 것 같습니다. 관리자 권한이 필요한 위치(C:\\Program Files 등)에 설치된 경우, C:\\Uchinoko 같은 쓰기 가능한 위치로 이동한 후 다시 시도해주세요.",
                "無法在任何位置建立工作資料夾。\n\n已嘗試的位置:\n‧{0}\n‧{1}\n\n這兩個位置似乎都沒有寫入權限。如果安裝在需要管理員權限的位置(例如 C:\\Program Files),請移動到可寫入的位置(例如 C:\\Uchinoko)後再試一次。",
                "无法在任何位置创建工作文件夹。\n\n已尝试的位置:\n‧{0}\n‧{1}\n\n这两个位置似乎都没有写入权限。如果安装在需要管理员权限的位置(例如 C:\\Program Files),请移动到可写入的位置(例如 C:\\Uchinoko)后再试一次。"
            } },
        };

        /// <summary>キーの文字列(現在の言語)を返す。未知キー/データ欠落時も
        /// 例外を投げず可視マーカーを返す(画面が固まるより手がかりが残る方を選ぶ)。</summary>
        internal static string S(string key)
        {
            return S(key, Current);
        }

        /// <summary>キーの文字列を、Current(現在表示中の言語)ではなく指定した言語で
        /// 返す(dev#150系の実機テストで発覚: 言語切替直後の案内メッセージが
        /// 「切替前の言語」で出ると、英語を選んだ人に日本語のメッセージが出て読めない。
        /// これから有効になる言語=ユーザーが今まさに選んだ言語で見せるための経路)。</summary>
        internal static string S(string key, Lang lang)
        {
            string[] arr;
            if (!Table.TryGetValue(key, out arr) || arr == null)
                return "??" + key + "??";
            string picked = PickFromArray(arr, lang);
            return picked ?? ("??" + key + "??");
        }

        internal static string F(string key, params object[] args)
        {
            return string.Format(S(key), args);
        }

        /// <summary>5言語配列から指定言語を選ぶ共通ロジック(S(key,lang)と
        /// TranslateProgressLabelで共有)。指定言語が範囲外/空なら索引0(ja)へ、
        /// それも空ならnullを返す(呼び出し側がキー無しマーカーか原文フォールバックか
        /// を選べるように、ここでは「??」を作らない)。</summary>
        private static string PickFromArray(string[] arr, Lang lang)
        {
            int idx = (int)lang;
            if (idx < 0 || idx >= arr.Length || string.IsNullOrEmpty(arr[idx]))
                return arr.Length > 0 && !string.IsNullOrEmpty(arr[0]) ? arr[0] : null;
            return arr[idx];
        }

        // ---------------- dev#304 裁定A(2026-07-30): 進捗ラベル(##PROGRESS##由来、
        // AppendLog内でstatusLabel.Textへ整形される文言)の辞書化 ----------------
        // 設計: work\speed_mission\ux\PROPOSAL.md §3提案4・§4。
        // キーはconvert.ps1(Progress関数呼び出し)が出す生の英語ラベル文字列そのもの
        // (Tableとは別辞書にして名前空間を分離する。UI部品のキー体系とは無関係)。
        // 「辞書にあれば翻訳、無ければ原文表示」のブラックリスト方式(ホワイトリストで
        // 未知ラベル=無表示を作らない、PROPOSAL.md §3提案4のリスク欄)。
        // 英語(index 1)は原文と同一の文字列にしてある: convert.ps1の生文字列を変える
        // 改修ではないため、英語UIでの見た目は従来と不変(dev#288 WP-UXIMPL由来の
        // 既存試験 RunProgressRelayChecks の期待文字列が変わらない設計上の理由でもある)。
        internal static readonly Dictionary<string, string[]> ProgressLabels = new Dictionary<string, string[]> {
            { "Preparing", new[] { "準備中", "Preparing", "준비 중", "準備中", "准备中" } },
            { "Fetching game data", new[] { "ゲームデータを取得中", "Fetching game data", "게임 데이터 가져오는 중", "正在取得遊戲資料", "正在获取游戏数据" } },
            { "Loading avatar", new[] { "アバターを読み込み中", "Loading avatar", "아바타 불러오는 중", "正在載入角色模型", "正在加载角色模型" } },
            { "Retargeting skeleton", new[] { "スケルトンをリターゲット中", "Retargeting skeleton", "스켈레톤 리타겟 중", "正在重新定位骨架", "正在重新定位骨架" } },
            { "Generating preview image", new[] { "プレビュー画像を生成中", "Generating preview image", "미리보기 이미지 생성 중", "正在產生預覽圖", "正在生成预览图" } },
            { "Skeleton + preview complete (parallel)", new[] { "スケルトン+プレビュー完了(並列)", "Skeleton + preview complete (parallel)", "스켈레톤+미리보기 완료(병렬)", "骨架+預覽完成(平行)", "骨架+预览完成(并行)" } },
            { "Generating MOD files", new[] { "MODファイルを生成中", "Generating MOD files", "모드 파일 생성 중", "正在產生 MOD 檔案", "正在生成 MOD 文件" } },
            { "Packaging complete, verifying result", new[] { "パッケージ化完了、結果を確認中", "Packaging complete, verifying result", "패키징 완료, 결과 확인 중", "封裝完成,正在確認結果", "打包完成,正在确认结果" } },
            { "Done", new[] { "完了", "Done", "완료", "完成", "完成" } },
            { "Checking previous conversion results", new[] { "前回の変換結果を確認中", "Checking previous conversion results", "이전 변환 결과 확인 중", "正在確認先前的轉換結果", "正在确认先前的转换结果" } },
            { "Final check", new[] { "最終確認中", "Final check", "최종 확인 중", "最終確認中", "最终确认中" } },
            // PR#307(dev#288 WP-UXIMPL提案1)の新中間マーカー8件
            { "Preparing template assets", new[] { "テンプレート素材を準備中", "Preparing template assets", "템플릿 자산 준비 중", "正在準備範本素材", "正在准备模板素材" } },
            { "Baking texture atlas", new[] { "テクスチャアトラスを生成中", "Baking texture atlas", "텍스처 아틀라스 생성 중", "正在產生紋理圖集", "正在生成纹理图集" } },
            { "Preparing material overrides", new[] { "マテリアルの上書きを準備中", "Preparing material overrides", "머티리얼 오버라이드 준비 중", "正在準備材質覆寫", "正在准备材质覆盖" } },
            { "Reading avatar data", new[] { "アバターデータを読み込み中", "Reading avatar data", "아바타 데이터 읽는 중", "正在讀取角色模型資料", "正在读取角色模型数据" } },
            { "Injecting avatar into outfit items", new[] { "アバターを衣装アイテムへ組み込み中", "Injecting avatar into outfit items", "아바타를 의상 아이템에 적용 중", "正在將角色模型套用到服裝項目", "正在将角色模型应用到服装项目" } },
            { "Compressing textures", new[] { "テクスチャを圧縮中", "Compressing textures", "텍스처 압축 중", "正在壓縮紋理", "正在压缩纹理" } },
            { "Building pak file", new[] { "pakファイルを構築中", "Building pak file", "pak 파일 빌드 중", "正在建立 pak 檔案", "正在构建 pak 文件" } },
            { "Running preflight checks", new[] { "事前検査を実行中", "Running preflight checks", "사전 점검 실행 중", "正在執行預檢", "正在执行预检查" } },
        };

        /// <summary>性別名など可変部を含む進捗ラベルのテンプレート。Patternは生ラベル
        /// 全体に一致する正規表現(先頭^末尾$固定)で、グループ1が可変部。可変部
        /// (convert.ps1の$Genders値、例: "Male"/"Female"/"Male, Female")自体は
        /// 翻訳しない(固有の内部識別子として扱う。日英中韓のどれでも同じ表記)。</summary>
        internal sealed class ProgressLabelTemplate
        {
            internal readonly Regex Pattern;
            internal readonly string[] Format;
            internal ProgressLabelTemplate(string pattern, string[] format)
            {
                Pattern = new Regex(pattern);
                Format = format;
            }
        }

        internal static readonly ProgressLabelTemplate[] ProgressLabelTemplates = new[] {
            new ProgressLabelTemplate(
                "^Retargeting skeleton \\+ preview \\(parallel: (.+)\\)$",
                new[] { "スケルトン+プレビューをリターゲット中(並列: {0})", "Retargeting skeleton + preview (parallel: {0})", "스켈레톤+미리보기 리타겟 중(병렬: {0})", "正在重新定位骨架+預覽(平行: {0})", "正在重新定位骨架+预览(并行: {0})" }),
            new ProgressLabelTemplate(
                "^Retargeting skeleton \\((.+)\\)$",
                new[] { "スケルトンをリターゲット中({0})", "Retargeting skeleton ({0})", "스켈레톤 리타겟 중({0})", "正在重新定位骨架({0})", "正在重新定位骨架({0})" }),
            new ProgressLabelTemplate(
                "^Generating preview image \\((.+)\\)$",
                new[] { "プレビュー画像を生成中({0})", "Generating preview image ({0})", "미리보기 이미지 생성 중({0})", "正在產生預覽圖({0})", "正在生成预览图({0})" }),
        };

        /// <summary>##PROGRESS##マーカーのラベル文字列(convert.ps1の生英語文字列)を
        /// 現在の表示言語(Strings.Current)へ翻訳する。辞書に無いラベルは原文のまま
        /// 返す(未知ラベル=無表示を作らないブラックリスト方式)。</summary>
        internal static string TranslateProgressLabel(string raw)
        {
            return TranslateProgressLabel(raw, Current);
        }

        /// <summary>テスト容易性のため、実際に使う辞書(ProgressLabels/
        /// ProgressLabelTemplates)を明示的に渡せる版。本番経路は下のオーバーロード
        /// (2引数)からこちらを呼ぶ。テストは意図的に壊した小さな辞書を渡して、
        /// フォールバックが原文を返すこと(無表示にならないこと)を確認できる。</summary>
        internal static string TranslateProgressLabel(string raw, Lang lang)
        {
            return TranslateProgressLabelFrom(raw, lang, ProgressLabels, ProgressLabelTemplates);
        }

        internal static string TranslateProgressLabelFrom(string raw, Lang lang,
            Dictionary<string, string[]> table, ProgressLabelTemplate[] templates)
        {
            if (string.IsNullOrEmpty(raw)) return raw;
            string[] arr;
            if (table.TryGetValue(raw, out arr) && arr != null)
            {
                string picked = PickFromArray(arr, lang);
                return picked ?? raw;   // 辞書エントリが壊れていても原文へフォールバック
            }
            if (templates != null)
            {
                for (int i = 0; i < templates.Length; i++)
                {
                    Match m = templates[i].Pattern.Match(raw);
                    if (!m.Success) continue;
                    string fmt = PickFromArray(templates[i].Format, lang);
                    if (fmt == null) return raw;
                    try { return string.Format(fmt, m.Groups[1].Value); }
                    catch (FormatException) { return raw; }
                }
            }
            return raw;   // 辞書に無いラベル(未知/新規追加分)は原文のまま表示
        }
    }


    public partial class MainForm : Form
    {
        TextBox vrmBox;
        TrackBar shoulderBar;
        Label shoulderLabel;
        TrackBar shadowBar;
        Label shadowLabel;
        CheckBox mergeFingersCheck;
        CheckBox unlitCheck;
        CheckBox twoSidedCheck;
        TextBox dropBonesBox;
        Button convertButton;
        Button matsButton;
        Label matsHintLabel;    // U51: 無効なボタンはツールチップが出ないので理由をここに出す
        Button previewButton;
        Button cancelButton;
        Button applyButton;
        CheckBox autoApplyCheck;   // 変換完了後に自動でPalworldへ適用(既定ON。settings_autoapply.txtに記憶)
        Button removeButton;
        Button deleteButton;
        Button kodawariToggle;
        Panel kodawariPanel;
        Button reportButton;   // dev#25/dev#42: 「問合せ」(メインUI唯一のサポート導線)
        string reportViewUrl;  // dev#42: 送信済み報告のview_url(このプロセス内のみ保持。
                                // 一度送信すれば、以後は問合せボタンから直接同じ場所を開ける)
        string reportId;       // dev#42: 送信済み報告ID(reportViewUrlとセットで保持。表示用)
        string lastSentBaseLog; // dev#42b(2026-07-29官能検査是正): 前回送信成功時点の
                                // BuildDiagnosticsText()生成結果(ユーザー編集前の素の文)。
                                // 次回問合せ時、現在の生成結果と比較してログの変化を検出し、
                                // 変化していれば再送(stage2)を既定で促すために使う
        PictureBox previewFront;
        PictureBox previewSide;
        TextBox logBox;
        Label statusLabel;
        Label updateLabel;   // dev#15(更新通知のみ): 新版検出時だけ表示するクリック可能ラベル
        // dev#216 WP1で新設した「今すぐ更新」ボタン。当初はアプリ内でDL・検証・展開まで
        // 行っていたが、適用エンジン(ランチャー)が2026-07-31のランチャー廃止で配布物から
        // 除去され、ダウンロードした内容を適用する者がいなくなった(実測確認済み)。
        // FIX38(2026-07-31)でダウンロード経路自体を削除し、updateLabelと同じく
        // 配布ページを開くだけのボタンへ変更した(FIX25推奨案)。
        Button updateNowButton;
        ProgressBar busyBar;
        // u54(2026-07-27): 配布物はBlender本体を同梱しない。起動時にFindBlender()の
        // 結果が実在しなければバックグラウンドでensure_blender.ps1を実行し、
        // ここに結果を持つ(失敗・キャンセル時はconvertButton等を無効化し続ける)。
        // dev#236(2026-07-30): 以前はここでモーダルダイアログ(BlenderSetupDialog)を
        // 出してUIをブロックしていたが、初回セットアップ中にポップアップ・モーダルを
        // 出さない裁定に伴い撤去した。blenderReadyの初期値をfalse(未確定)にし、
        // 既存のボタン無効化ゲート(UpdateButtonStates)がそのまま「準備完了まで
        // 変換を始めさせない」役を果たす。進捗は常設のstatusLabel/busyBarへ出す。
        bool blenderReady;
        string blenderSetupMessage;
        // dev#236: 起動時チェック/取得と「Blenderを再取得」ボタンの二重起動を防ぐ
        bool blenderSetupRunning;
        // dev#236: アプリ終了時にセットアップ用サブプロセスを孤児化させないための追跡
        // (marker検証はensure_blender.ps1側にあるので、途中終了しても次回起動時に
        // 自己修復される。PR #231の自己修復動作はそのまま)
        Process blenderSetupProc;
        // dev#236: Blender未セットアップのままD&Dされたファイルを、セットアップ完了後に
        // 自動で続行するためのキュー(ユーザーに聞き直さない。1件のみ、後勝ち)
        Action pendingBlenderReadyAction;
        Button blenderRetryButton;
        Process runningProc;
        bool licenseConfirmed;   // このアバターの規約確認(job.jsonに記憶)
        bool silentPreview;      // 自動プレビュー時は完了ダイアログを出さない
        // dev#288 WP-UXIMPL(2026-07-30、提案2): フル変換パスでもPhase1完了
        // (Progress 39%到達)時点でプレビュー画像を再読込する。従来は
        // OnPipelineDone(プロセス終了=全工程完了後)でしかLoadPreviews()が
        // 呼ばれず、設定変更後に直接「フル変換」した場合、新しい設定を反映した
        // 新プレビューが39%時点で既に書き終わっているのに画面には96〜100%まで
        // 古い画像が表示され続けていた(PROPOSAL.md 2.2節)。
        // currentPipelineJobDir: RunPipeline開始時のjobDirをAppendLog(進捗行を
        // 処理する側)へ届けるためのフィールド(AppendLogはRunPipelineのローカル
        // 変数を直接参照できないため)。
        // earlyPreviewLoadedThisRun: 1回だけ呼ぶためのフラグ(RunPipeline開始時に
        // falseへリセット)。39%以降のマーカーが何度来ても再読込は1回に留める。
        string currentPipelineJobDir;
        bool earlyPreviewLoadedThisRun;

        // ---- バックグラウンド作業(ディスク読み込みだけ)の管理 ----
        // runningProc(変換プロセス)とは**完全に別系統**にしてある。ここで走るのは
        // ファイル読み込みとハッシュ計算だけで、「変換を中止」ボタン・終了時の確認
        // ダイアログ・進捗バーには一切関与しない(ユーザーの変換を裏の処理が殺す・
        // 裏の処理のせいで終了時に確認が出る、といった事故を構造的に起こさないため)。
        // 世代番号は「古い処理の結果が新しい選択を上書きする」事故を防ぐためのもの。
        // これらのフィールドはUIスレッドからのみ読み書きすること。
        int avatarLoadGen;       // アバター読み込みの世代(これと違う結果は捨てる)
        bool avatarLoading;      // 読み込み中(設定が画面に載る前に変換させない)
        int appliedStatusGen;    // 「適用中のMOD」照合の世代
        string backgroundError;  // 直近のバックグラウンド失敗(次の操作時に見せる)
        // 2026-07-26追加: パイプライン(convert_noue.py等)が##AVATAR_WARNING##
        // マーカーで出す「ビルドは通ったが見た目が崩れる可能性がある」警告
        // (UVタイル境界をまたぐ面の除外等)。ログ欄に流れるだけだと見落とされる
        // ため、変換完了時にダイアログでも明示提示する(AppendLog/OnPipelineDone参照)。
        List<string> pipelineWarnings = new List<string>();

        // 2026-07-26 LX追加: 「ログをコピー」が不具合報告として役に立つためのセッション全体ログ。
        // logBoxは工程(RunPipeline/RunUnityExport)ごとにClear()されるため、
        // Unity輸出→変換のように工程をまたぐと直前の工程の記録が消えてしまっていた
        // (実例: shapell_Osakiの帽子が原点に落ちる不具合で、送られてきたログが
        //  Unity輸出だけで終わり、原因のある変換工程の記録が入っていなかった)。
        // このバッファは「同じアバターを触っている一連の作業」の間はクリアされない。
        // クリアされるのは新しいアバターを選び直した時だけ(SetVrm(path, newSession:true)。
        // Unity輸出からの続きの取り込み(OnUnityExportDone→SetVrm(fbx, false))はクリアしない)。
        StringBuilder sessionLog = new StringBuilder();
        // BOOTHのメッセージ欄に非エンジニアが貼れる分量の上限(文字数)。
        // 通常の「フル変換」1回のログだけで実測5万〜9万文字程度あるため
        // (work\配下の実ログで確認済み)、それを潰さない程度に余裕を持たせつつ、
        // 同一セッション内で何度も変換をやり直した場合の際限ない肥大は止める。
        // 上限に達したら「直近の症状」を優先し、古い方(先頭)から切り捨てる
        // (ユーザーが今困っている操作は大抵そのセッションの最後の工程のため)。
        const int SessionLogCapChars = 500000;

        // ---------------- ログ欄フォントの安全な選定(2026-07-27 LX追加) ----------------
        // 発端: オーナーがWindows Sandbox(まっさらなWindows 11)で試したところ、
        // ログ欄の日本語が全部□(欠字)になった。ウィンドウタイトルやボタンの日本語は
        // 正常に出ていたので、システム全体が日本語を描けないのではなく、ログ欄に
        // 明示指定していた"Consolas"(ラテン専用の等幅フォント、日本語グリフを持たない)
        // 固有の問題だった。通常のWindowsではGDIのフォントリンクによる代替が効いて
        // 気づかなかったが、Sandboxの最小構成ではそれが効かなかった。
        //
        // 再発防止の方針: 「このフォントなら大丈夫だろう」という決め打ちを二度としない。
        // 候補フォントを複数用意し、実行時に実機へGDI直接問い合わせ(GetGlyphIndicesW)で
        // 「代表的な日本語1文字(あ)のグリフを本当に持っているか」を確認してから採用する。
        // 名前が一致してもGDI+がフォントを黙って別物に差し替えることがある
        // (Font.Nameが要求と違う値になる)ため、まずその名前一致も確認する。
        // 等幅を優先するが(ログは桁揃えが読みやすさに効く)、
        // どの候補も使えない場合はタイトルバー/ボタンと同じデフォルトUIフォントへ委ねる
        // (等幅よりも「確実に読めること」を優先する)。

        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        static extern uint GetGlyphIndicesW(IntPtr hdc, string lpstr, int c,
            [Out] ushort[] pgi, uint fl);
        [DllImport("gdi32.dll")]
        static extern IntPtr SelectObject(IntPtr hdc, IntPtr hgdiobj);
        [DllImport("gdi32.dll")]
        static extern bool DeleteObject(IntPtr hObject);
        const uint GGI_MARK_NONEXISTING_GLYPHS = 1;
        const uint GDI_ERROR = 0xFFFFFFFF;
        const ushort MissingGlyphMarker = 0xFFFF;

        // 「あ」(代表的な日本語文字)のグリフをこのフォントが実際に持っているかを、
        // GDIへ直接問い合わせて確認する。Graphics.DrawString等の高レベルAPIは
        // Uniscribe/DirectWrite側で別フォントへのフォールバック描画を行うことがあり
        // 「本当にこのフォントが持っているか」の判定に使えないため、
        // 低レベルのGetGlyphIndicesW(フォールバックなし)で直接確認する。
        static bool FontHasJapaneseGlyph(Font f)
        {
            try
            {
                using (var bmp = new Bitmap(1, 1))
                using (var g = Graphics.FromImage(bmp))
                {
                    IntPtr hdc = g.GetHdc();
                    try
                    {
                        IntPtr hFont = f.ToHfont();
                        IntPtr old = SelectObject(hdc, hFont);
                        try
                        {
                            var buf = new ushort[1];
                            uint ret = GetGlyphIndicesW(hdc, "あ", 1, buf, GGI_MARK_NONEXISTING_GLYPHS);
                            return ret != GDI_ERROR && buf[0] != MissingGlyphMarker;
                        }
                        finally
                        {
                            SelectObject(hdc, old);
                            DeleteObject(hFont);
                        }
                    }
                    finally { g.ReleaseHdc(hdc); }
                }
            }
            catch (Exception) { return false; }
            // ここに来る例外(GDIハンドル不足等)は「安全側」に倒し、
            // 「このフォントは使えない」= 次の候補へ、として扱う
        }

        // 候補名で実際にFontを作り、(1)要求どおりの名前で解決できたか
        // (GDI+の黙った差し替えを検出)、(2)日本語グリフを本当に持っているか、
        // の両方を確認してから採用する。どちらか一方でも満たさなければ次点へ回す
        static bool TryResolveJapaneseFont(string name, float size, out Font font)
        {
            font = null;
            try
            {
                var f = new Font(name, size);
                if (!string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    f.Dispose();
                    return false;
                }
                if (!FontHasJapaneseGlyph(f))
                {
                    f.Dispose();
                    return false;
                }
                font = f;
                return true;
            }
            catch (Exception) { return false; }
        }

        static Font ResolveLogFont()
        {
            // 等幅(桁揃え)を優先する順。ローカライズ済みWindowsではFontFamily名が
            // 日本語表記(例:「ＭＳ ゴシック」)で登録されていることがあるため、
            // 英語名・日本語名の両方を候補に入れておく
            string[] candidates =
            {
                "MS Gothic", "ＭＳ ゴシック",         // 日本語固定ピッチ(第一候補、等幅を保てる)
                "MS UI Gothic", "ＭＳ Ｐゴシック",
                "Yu Gothic UI", "游ゴシック UI",       // 比較的新しい環境の既定に近い(可変幅)
                "Meiryo UI", "メイリオ",               // 古めの環境でも広く入っている(可変幅)
                "BIZ UDゴシック",                      // Windows 11 22H2以降の同梱UDフォント
            };
            foreach (string name in candidates)
            {
                Font f;
                if (TryResolveJapaneseFont(name, 9f, out f)) return f;
            }
            // どの候補も実在しない/日本語グリフを持たない場合の最終手段。
            // タイトルバーやボタンと同じデフォルトUIフォントへ委ねる
            // (このフォントはOSが動的に解決するため、このプロセスが起動できている
            //  時点で日本語含め確実に描画できる。等幅は失うが読めない等幅よりまし)
            return (Font)SystemFonts.DefaultFont.Clone();
        }

        // dev#106(rd_93緊急修正B): 英語UIでボタン文字があふれる問題(cancelButton幅100に
        // "Cancel Conversion"17字等)の是正。値をそれっぽく決め打ちしない(CLAUDE.md
        // 「値を寄せる修正は却下」)ため、ボタンが実際に使うのと同じフォント
        // (SystemFonts.DefaultFont、このフォームはFontを明示上書きしていない)で
        // 5言語すべての文言をGDI実測し、最長のものが収まる幅を返す。paddingは
        // WinFormsテーマ付きボタンの内側余白の実測余裕分(既定8.25ptフォントで
        // 概ね20px前後必要という経験則+安全マージン)
        static int MeasureButtonWidth(string i18nKey, int minWidth)
        {
            int max = minWidth;
            string[] variants;
            if (!Strings.Table.TryGetValue(i18nKey, out variants) || variants == null) return minWidth;
            foreach (string s in variants)
            {
                if (string.IsNullOrEmpty(s)) continue;
                Size sz = TextRenderer.MeasureText(s, SystemFonts.DefaultFont);
                int need = sz.Width + 28;   // 左右パディング+安全マージン
                if (need > max) max = need;
            }
            return max;
        }

        // dev#133(i18n_overflow_lint.py検出): 英語lblDrop("Drop Bones (Advanced):"
        // 23字)が固定Width=110からあふれる(実測117px、余白差引後108pxで9pxオーバー)。
        // MeasureButtonWidth(dev#106)と同じ考え方で、Labelが実際に使うのと同じ
        // フォント(SystemFonts.DefaultFont)で5言語すべてを実測して最長幅を返す。
        // paddingはi18n_overflow_lint.pyのPADDING_PX["Label"]=2に合わせつつ、
        // TextRenderer.MeasureTextとlinter側のGetTextExtentPoint32W実測の差を
        // 吸収する安全マージンを加える(値を寄せるのではなく両実測系の差の吸収)。
        static int MeasureLabelWidth(string i18nKey, int minWidth)
        {
            int max = minWidth;
            string[] variants;
            if (!Strings.Table.TryGetValue(i18nKey, out variants) || variants == null) return minWidth;
            foreach (string s in variants)
            {
                if (string.IsNullOrEmpty(s)) continue;
                Size sz = TextRenderer.MeasureText(s, SystemFonts.DefaultFont);
                int need = sz.Width + 6;   // Label余白2px相当+安全マージン
                if (need > max) max = need;
            }
            return max;
        }

        string appRoot;      // 配布ルート(exeの場所)
        string workRoot;
        // dev#298: workRoot決定の経緯(3点セット: 自動→フォールバック→ログ)。
        // C:\Program Files\配下等、標準ユーザーが書き込めない場所へインストールされた
        // 環境でNew-Item/Directory.CreateDirectoryがUnauthorizedAccessExceptionで
        // 落ちる不具合(実報告R7GJY5W3)への対応。WorkRootResolveLogic.Resolve()
        // (この直後のstatic classの純粋ロジック)がappRoot\workの書き込み可否を
        // ProbeWorkRootWritable()(実I/O)で試し、不可なら%LOCALAPPDATA%\Uchinoko\work
        // (ユーザー書き込み可能領域、TryGetShortBlenderPathの%LOCALAPPDATA%\Uchinoko\...
        // と同じ置き場の流儀)へフォールバックする。結果はここに保存し、
        // logBox生成後(CheckPathHealthOnStartup/LogPathHealthForThisRun)に必ずログへ出す。
        bool workRootUsedFallback;
        bool workRootFailed;      // 両方とも書き込めない(稀。ログ+明示エラーで案内、変換系ボタンは無効化)
        string workRootPrimaryPath;
        string workRootFallbackPath;
        string workRootPrimaryError;
        string workRootFallbackError;
        string paksDirCache;

        // 排他制御: ゲームへは常にこの固定名で1つだけ入れる(適用=上書き、解除=削除)
        const string InstallName = "Uchinoko_P.pak";
        // 旧名の残骸も適用/解除の対象にする(v1.x DiveToPalworld時代 / さらに前のvrm2palworld時代)。
        // 旧版で入れたMODを新版で確実に解除できるよう、両方とも対象に残す
        static readonly string[] LegacyInstallNames = { "DiveToPalworld_P.pak", "VRM2Palworld_P.pak" };
        const string ToolVersion = "v2.2.13";
        // dev#42(2026-07-29): 画面にメールアドレス・GitHub Issues URLを一切出さない
        // 方針に変更したため、旧GithubIssuesUrl定数(画面のcontactLabelでのみ使用)は
        // 参照が無くなり削除した。問い合わせは「問合せ」ボタン→ShowSupportDialog()の
        // 送信フローに一本化されている。
        // 問い合わせ用メールアドレス。実アドレスはこのリポジトリに一切含めない
        // (空文字のプレースホルダのまま追跡する)。ビルド時にのみ
        // devtools\support_contact.txt(非公開、Pubへは同期されない)から
        // app\build_app.ps1 が差し込む。Pub(公開GitHub)側は devtools\ 自体が
        // 同期対象外のため、この定数は常に空文字のまま公開される。
        const string SupportEmail = "";
        // dev#25: 不具合報告の送信先(Cloudflare Worker。API契約は work\wp_report\REPORT.md が正)。
        // 環境変数 D2P_REPORT_BASEURL で上書き可能(疎通しない偽URLを与えれば
        // オフライン縮退の試験ができる。通常ユーザーは触らない)。
        const string ReportBaseUrlDefault = "https://report.osakishokai.com";

        static string GetReportBaseUrl()
        {
            string env = Environment.GetEnvironmentVariable("D2P_REPORT_BASEURL");
            if (!string.IsNullOrEmpty(env)) return env.TrimEnd('/');
            return ReportBaseUrlDefault;
        }

        // dev#15(更新通知のみ。セルフアップデートは今回スコープ外): 配布基盤の版情報。
        // スキーマ: {"latest": "2.1.0", "versions": [{version,date,filename,sha256,size,url}, ...]}
        // ("latest"にはvプレフィックス無しで入っている実測値を確認済み。ToolVersionの
        // "v2.0.0"表記とは比較関数(IsNewerVersion)側でv有無を吸収する)
        const string VersionCheckUrl = "https://dl.osakishokai.com/versions.json";
        // 通知クリック時に開く入手先(BOOTH新店ページ)。GitHub Releases等へは飛ばさない
        const string UpdateDownloadPageUrl = "https://osaki-vrc.booth.pm/items/8662197";
        // FIX38(2026-07-31): 旧TrustedCdnUrlPrefix/GithubReleaseOwnerRepo(dev#216 WP1、
        // アプリ内ダウンロードのCDN許可リスト/GitHub Releasesフォールバック先)は、
        // ダウンロード経路自体の削除に伴い唯一の利用元(SelfUpdateクラス)を失ったため
        // 削除した。

        // 2026-07-29 WP-ico: タイトルバーアイコンの共通ヘルパー。ビルド時に
        // build_app.ps1 が /win32icon: で埋め込んだアイコンを、実行中のexe自身から
        // 逆に取り出して各Formへ設定する(ico\の画像を直接読み込まないのは、配布物が
        // exe単体になっても崩れないようにするため)。csc.exeでのコンパイル自体は
        // アイコン未埋め込み(ビルド後のexeを実行して初めて有効)なので、
        // ExtractAssociatedIconが失敗する状況(開発中の別経路実行等)を想定してnull安全にする。
        // MainForm・ShowSupportDialogのForm等、このアプリが開くすべてのFormで
        // このヘルパーを使うこと(個別にICO読み込みを書かない)。
        // dev#236: BlenderSetupDialog(旧ネストクラス)はモーダル撤去に伴い削除した。
        static Icon TryGetAppIcon()
        {
            try { return Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch (Exception) { return null; }
        }

        // ---------------- dev#29: GUI多言語化(言語決定・永続化) ----------------
        // 短縮ヘルパー。Strings.S/Strings.Fを呼ぶだけだが、~150箇所の置換を
        // "T(...)"/"TF(...)" で済ませるために用意する(既存コードの流儀
        // (WhatToDo系の短いstaticヘルパー)に合わせる)
        static string T(string key) { return Strings.S(key); }
        static string TF(string key, params object[] args) { return Strings.F(key, args); }

        /// <summary>純関数。CultureInfo名から表示言語を判定する(テスト容易性のため
        /// 文字列入力のみに依存し、実際のCultureInfo取得はDetermineInitialLang側で行う)。
        /// ja→Ja / ko→Ko / zh-Hant系(zh-TW/zh-HK/zh-MO/Hant)→ZhTW /
        /// zh(その他、Hans系含む)→ZhCN / それ以外・null・不正→En。
        /// 単体表(7ケース)は Uchinoko.exe --check-i18n で機械検査できる(CheckI18nCli参照)。</summary>
        internal static Lang DetectLangFromCulture(string cultureName)
        {
            if (string.IsNullOrEmpty(cultureName)) return Lang.En;
            string n = cultureName.ToLowerInvariant();
            if (n.StartsWith("ja")) return Lang.Ja;
            if (n.StartsWith("ko")) return Lang.Ko;
            if (n.StartsWith("zh"))
            {
                if (n.Contains("hant") || n.Contains("-tw") || n.Contains("-hk") || n.Contains("-mo"))
                    return Lang.ZhTW;
                return Lang.ZhCN;   // Hans系、またはバリアント無しの単なる"zh"
            }
            return Lang.En;
        }

        // settings_language.txt に保存する短いコード("ja"/"en"/"ko"/"zh-TW"/"zh-CN")。
        // 既存のsettings_*.txt(autoapply/lastvrm/paksdir等)と同じ「appRoot直下に平テキスト」
        // の流儀に合わせる
        static string LangToCode(Lang lang)
        {
            switch (lang)
            {
                case Lang.Ja: return "ja";
                case Lang.Ko: return "ko";
                case Lang.ZhTW: return "zh-TW";
                case Lang.ZhCN: return "zh-CN";
                default: return "en";
            }
        }

        static bool TryParseLangCode(string code, out Lang lang)
        {
            switch ((code ?? "").Trim())
            {
                case "ja": lang = Lang.Ja; return true;
                case "en": lang = Lang.En; return true;
                case "ko": lang = Lang.Ko; return true;
                case "zh-TW": lang = Lang.ZhTW; return true;
                case "zh-CN": lang = Lang.ZhCN; return true;
                default: lang = Lang.En; return false;
            }
        }

        static string LanguageSettingFile(string appRootPath)
        {
            return Path.Combine(appRootPath, "settings_language.txt");
        }

        // 既定言語の決定: settings_language.txt があればそれを最優先。
        // 無い/読めない/不正な内容なら CultureInfo.CurrentUICulture から判定する
        // (初回起動時、日本語OSならja、それ以外は既定でen等になる)
        static Lang DetermineInitialLang(string appRootPath)
        {
            try
            {
                string f = LanguageSettingFile(appRootPath);
                if (File.Exists(f))
                {
                    string v = File.ReadAllText(f, Encoding.UTF8).Trim();
                    Lang parsed;
                    if (TryParseLangCode(v, out parsed)) return parsed;
                }
            }
            catch (Exception) { }
            return DetectLangFromCulture(CultureInfo.CurrentUICulture.Name);
        }

        void SaveLanguageSetting(Lang lang)
        {
            try { File.WriteAllText(LanguageSettingFile(appRoot), LangToCode(lang), new UTF8Encoding(false)); }
            catch (Exception) { }
        }

        // ---------------- dev#173: 言語切替の即時反映(ApplyLanguage) ----------------
        // 以前は「保存だけ行い、実際の表示切替は次回起動時」という仕様だった
        // (Strings.Currentは次回起動まで更新しない設計で、切替直後の確認メッセージだけは
        // dev#150系の実機テストを受けて選択直後の言語で見せる対処療法を入れていた)。
        // ここでは選択した瞬間に画面そのものを差し替える。
        //
        // 生成時に Text = T("Key") / ツールチップを設定したコントロールは、宣言の
        // 直後に RegisterI18nText/RegisterI18nTip を1行足して (Control, Key) を憶えて
        // おく。devtools\i18n_overflow_lint.py は "name = new ControlType { ... Text =
        // T(\"Key\") ... }" というソース上のリテラル形をそのままパースする契約なので、
        // 宣言行自体は一切ラップしない(ラップするとリンターの走査対象からコントロールが
        // 消え、オーバーフロー検出が静かに効かなくなる)。
        ToolTip tip;
        List<KeyValuePair<Control, string>> i18nTextControls = new List<KeyValuePair<Control, string>>();
        List<KeyValuePair<Control, string>> i18nTooltipControls = new List<KeyValuePair<Control, string>>();
        string pendingUpdateVersion;   // ApplyLanguage時にShowUpdateNoticeを再適用するため保持(dev#15の更新通知と共有)

        void RegisterI18nText(Control c, string key)
        {
            i18nTextControls.Add(new KeyValuePair<Control, string>(c, key));
        }

        void RegisterI18nTip(Control c, string key)
        {
            i18nTooltipControls.Add(new KeyValuePair<Control, string>(c, key));
            tip.SetToolTip(c, T(key));
        }

        // langCombo選択時に呼ぶ。5言語共通の1経路(言語ごとの分岐は書かない)。
        //   1) Strings.Current切替+設定ファイル保存
        //   2) ウィンドウタイトル・登録済みの静的Text/Tooltipを再適用
        //   3) ListViewの列見出しを再設定
        //   4) 状態に依存する表示(statusLabel/matsHintLabel/appliedLabel/kodawariToggle/
        //      updateLabel)は、実際にその表示を決めている既存メソッドを呼び直して
        //      再計算させる(表示を決める判定ロジックをここへ二重化しない)
        void ApplyLanguage(Lang newLang)
        {
            Strings.Current = newLang;
            SaveLanguageSetting(newLang);

            Text = "Uchinoko for Palworld " + ToolVersion + " - " + T("TitleSubtitle");

            foreach (KeyValuePair<Control, string> kv in i18nTextControls)
                kv.Key.Text = T(kv.Value);
            foreach (KeyValuePair<Control, string> kv in i18nTooltipControls)
                tip.SetToolTip(kv.Key, T(kv.Value));

            if (pakList != null && pakList.Columns.Count == 4)
            {
                pakList.Columns[0].Text = T("ColAvatar");
                pakList.Columns[1].Text = T("ColFile");
                pakList.Columns[2].Text = T("ColSize");
                pakList.Columns[3].Text = T("ColCreatedAt");
            }

            kodawariToggle.Text = (kodawariPanel.Visible ? "▲" : "▼") + " " + T("LabelKodawari");

            if (updateLabel.Visible && pendingUpdateVersion != null)
                ShowUpdateNotice(pendingUpdateVersion);

            UpdateAppliedStatus();
            UpdateButtonStates();
        }

        public MainForm()
        {
            appRoot = Path.GetDirectoryName(Application.ExecutablePath);
            // 開発中はリポジトリ直下から実行される想定(app\..)
            if (!Directory.Exists(Path.Combine(appRoot, "pipeline")))
            {
                string parent = Path.GetDirectoryName(appRoot);
                if (parent != null && Directory.Exists(Path.Combine(parent, "pipeline")))
                    appRoot = parent;
            }
            {
                // dev#298: 自動発見(appRoot\work)→書き込み不可なら手動指定を待たず
                // 自動フォールバック(%LOCALAPPDATA%\Uchinoko\work、ユーザー書き込み可能領域)
                // →判定結果は必ずログへ(外部依存パスの原則の三点セット。フォールバックは
                // 「壊れないための唯一の選択」なのでUI確認は不要、CLAUDE.md「曖昧なら聞く」の
                // 対象外)。両方とも書けない場合だけはユーザー操作が要るので明示的に警告する
                // (workRootFailed、CheckPathHealthOnStartupで判定・案内)。
                string primaryWork = Path.Combine(appRoot, "work");
                string fallbackWork = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Uchinoko", "work");
                var res = WorkRootResolveLogic.Resolve(primaryWork, fallbackWork, ProbeWorkRootWritable);
                workRoot = res.Path;
                workRootUsedFallback = res.UsedFallback;
                workRootFailed = res.Failed;
                workRootPrimaryPath = res.PrimaryPath;
                workRootFallbackPath = res.FallbackPath;
                workRootPrimaryError = res.PrimaryError;
                workRootFallbackError = res.FallbackError;
            }
            // dev#29: UI文字列の言語をここで確定する(以降の全コントロール生成が
            // Strings.Current を参照するため、他のどの処理より先に決める必要がある)
            Strings.Current = DetermineInitialLang(appRoot);

            // dev#42 item5: ウィンドウタイトルにツール版を連結する。ToolVersion自体の値は
            // devtools\release.py がリリース時にスタンプするので、ここでは連結するだけ。
            // "Uchinoko for Palworld"(製品名)とToolVersionは全言語共通(翻訳しない)
            Text = "Uchinoko for Palworld " + ToolVersion + " - " + T("TitleSubtitle");
            // dev#216 WP1: 更新ボタン/ステータス/プログレスバーの新設行(Top=848)を
            // 確保するため900→930へ拡張(既存コントロールは全てTop基準の絶対配置
            // なので、この変更で他要素の位置は一切動かない)
            Width = 1100; Height = 930;
            Icon = TryGetAppIcon();
            AllowDrop = true;
            DragEnter += OnDragEnter;
            DragDrop += OnDragDrop;

            tip = new ToolTip();

            // ---- 1行目: VRM ----
            var lblVrm = new Label { Left = 12, Top = 15, Width = 70, Text = T("LabelAvatar") };
            RegisterI18nText(lblVrm, "LabelAvatar");
            vrmBox = new TextBox { Left = 80, Top = 12, Width = 650, Name = "vrmBox" };
            var browse = new Button { Left = 738, Top = 10, Width = 90, Text = T("BtnBrowse"), Name = "browse" };
            RegisterI18nText(browse, "BtnBrowse");
            browse.Click += delegate
            {
                using (var dlg = new OpenFileDialog
                {
                    Filter = T("FileFilterAvatar"),
                    Title = T("DlgTitleChooseAvatarFile")
                })
                {
                    if (dlg.ShowDialog() != DialogResult.OK) return;
                    string f = dlg.FileName.ToLower();
                    if (f.EndsWith(".prefab"))
                        RunUnityExport(dlg.FileName);
                    else
                        SetVrm(dlg.FileName);
                }
            };
            // dev#42 item6: Labelの既定UseMnemonic=trueだと単独の"&"がニーモニック
            // (次の1文字を加速キー扱いにして下線・"&"自体を消す)として解釈され、
            // "(D&DでもOK)" が "(DDでもOK)" に化けて見える。この画面のLabelに
            // アクセラレータキーは不要なので、方式をUseMnemonic=falseに統一する
            // (statusLabelの「D&DでOK」も同じ理由で同じ方式を採る)
            var dropHint = new Label { Left = 900, Top = 15, Width = 176, Text = T("HintDragDrop"), UseMnemonic = false };
            RegisterI18nText(dropHint, "HintDragDrop");

            // ---- 2行目: メイン操作 ----
            // dev#106: 以前はconvertButton(12,幅200)/cancelButton(220,幅100)/
            // status系(330〜1070固定)という決め打ちレイアウトだったが、英語UIで
            // BtnCancelConvert("Cancel Conversion"17字)が幅100に収まらず文字が
            // あふれていた。ここから右は「必要な分だけ広げ、その分だけ隣を押し出す」
            // 連鎖レイアウトに変更(既存の右端1070=330+740は変えず、その中で吸収する)
            const int mainRowRight = 1070;   // status/busyBarの従来の右端(330+740)を維持
            int convertWidth = MeasureButtonWidth("BtnFullConvert", 200);
            convertButton = new Button { Left = 12, Top = 44, Width = convertWidth, Height = 36, Text = T("BtnFullConvert"), Name = "convertButton" };
            RegisterI18nText(convertButton, "BtnFullConvert");
            convertButton.Click += delegate { RunPipeline(false, false, false); };
            int cancelWidth = MeasureButtonWidth("BtnCancelConvert", 100);
            int cancelLeft = convertButton.Right + 8;   // 元の12+200=212→220と同じ8pxの間隔を踏襲
            cancelButton = new Button { Left = cancelLeft, Top = 44, Width = cancelWidth, Height = 36, Text = T("BtnCancelConvert"), Enabled = false, Name = "cancelButton" };
            RegisterI18nText(cancelButton, "BtnCancelConvert");
            cancelButton.Click += delegate
            {
                if (runningProc == null) return;
                if (MessageBox.Show(T("ConfirmCancelConvertBody"), T("TitleConfirm"),
                        MessageBoxButtons.YesNo) == DialogResult.Yes)
                    KillConversion();
            };
            int statusLeft = cancelButton.Right + 10;   // 元の320→330と同じ10pxの間隔を踏襲
            int statusWidth = mainRowRight - statusLeft;
            // 実進捗バー: convert.ps1が出す ##PROGRESS## マーカー(工程の区間割当+
            // クック工程はUEログの実測)で0〜100%を刻む
            busyBar = new ProgressBar
            {
                Left = statusLeft, Top = 46, Width = statusWidth, Height = 12,
                Style = ProgressBarStyle.Continuous, Minimum = 0, Maximum = 100,
                Visible = false
            };
            // UseMnemonic=false: dropHintと同じ理由(このLabelに動的に代入する
            // 「VRMファイルを入れてください(D&DでOK)」の"&"がニーモニックとして
            // 消費されるのを防ぐ。コントロール作成時に一度設定すれば以降のText代入
            // すべてに効くので、代入箇所ごとに"&&"エスケープを散らす必要がない
            statusLabel = new Label { Left = statusLeft, Top = 62, Width = statusWidth, Text = T("StatusPromptVrm"), UseMnemonic = false };
            // u54: Blenderセットアップの失敗/キャンセル時だけ表示する再試行ボタン
            // (アプリを再起動しなくても取得をやり直せるようにする)。dev#106: 表示位置は
            // busyBar/statusLabelと同じ帯(cancelButtonの右隣)なので、固定値330ではなく
            // statusLeftに追従させる(cancelButtonが英語UIで広がった時に重なるのを防ぐ)
            blenderRetryButton = new Button
            {
                Left = statusLeft, Top = 44, Width = MeasureButtonWidth("BtnBlenderRetry", 160), Height = 36,
                Text = T("BtnBlenderRetry"), Visible = false
            };
            RegisterI18nText(blenderRetryButton, "BtnBlenderRetry");
            blenderRetryButton.Click += delegate { EnsureBlenderReadyOnStartup(); UpdateButtonStates(); };
            RegisterI18nTip(blenderRetryButton, "TipBlenderRetry");

            // ---- 3行目: こだわり設定(普段は畳んである) ----
            kodawariToggle = new Button { Left = 12, Top = 88, Width = 150, Height = 26, Text = "▼ " + T("LabelKodawari"), Name = "kodawariToggle" };
            kodawariToggle.Click += delegate
            {
                kodawariPanel.Visible = !kodawariPanel.Visible;
                kodawariToggle.Text = (kodawariPanel.Visible ? "▲" : "▼") + " " + T("LabelKodawari");
                LayoutContentArea();
            };

            // 内部互換性のためにフィールドを初期化（UIには表示しない）
            shoulderBar = new TrackBar { Minimum = -20, Maximum = 20, Value = 0 };
            shoulderLabel = new Label { Text = "0" };
            mergeFingersCheck = new CheckBox { Checked = false, Name = "mergeFingersCheck" };
            unlitCheck = new CheckBox { Checked = false, Name = "unlitCheck" };
            twoSidedCheck = new CheckBox { Checked = true, Name = "twoSidedCheck" };

            kodawariPanel = new Panel
            {
                Left = 12, Top = 118, Width = 1058, Height = 80,
                BorderStyle = BorderStyle.FixedSingle, Visible = false
            };
            var lblShadow = new Label { Left = 8, Top = 12, Width = 110, Text = T("LabelShadowStrength") };
            RegisterI18nText(lblShadow, "LabelShadowStrength");
            shadowBar = new TrackBar
            {
                Left = 120, Top = 6, Width = 300, Minimum = 0, Maximum = 100,
                Value = 30, TickStyle = TickStyle.None, AutoSize = false, Height = 28
            };
            shadowLabel = new Label { Left = 430, Top = 12, Width = 50, Text = "30%" };
            shadowBar.ValueChanged += delegate { shadowLabel.Text = shadowBar.Value + "%"; };
            RegisterI18nTip(shadowBar, "TipShadowBar");

            // dev#106: BtnMatsOnly英語("Update Shadow Only (Fast)"25字)は幅180だと
            // あふれる。実測幅で広げ、右隣のmatsHintLabelをその分押し出す
            // (パネル内の従来の右端1050=690+360は維持)
            int matsButtonWidth = MeasureButtonWidth("BtnMatsOnly", 180);
            matsButton = new Button { Left = 500, Top = 6, Width = matsButtonWidth, Height = 30, Text = T("BtnMatsOnly"), Name = "matsButton" };
            RegisterI18nText(matsButton, "BtnMatsOnly");
            matsButton.Click += delegate { RunPipeline(false, true, false); };
            // U51: noueでも押せるようになった(devtools\fast_repack.py が前回の中間成果を
            // 再利用してMODだけ作り直す)。2026-07-25 実測(Seed-san / 742MBのpak):
            //   「影のみ更新」50〜55秒(pak書き出し約35秒 + 最終チェック約17秒)
            //   「フル変換」 364秒
            // 数字は必ず実測に合わせること(古い「約1分/UEモード専用」はUE時代の値だった。
            // 数字はTipMatsButtonキー内に埋め込み済み、5言語とも同じ実測値を使うこと)
            RegisterI18nTip(matsButton, "TipMatsButton");
            const int matsRowRight = 1050;   // パネル内の従来の右端(690+360)を維持
            int matsHintLeft = Math.Max(690, matsButton.Right + 10);
            matsHintLabel = new Label { Left = matsHintLeft, Top = 12, Width = matsRowRight - matsHintLeft, Text = "" };

            int lblDropWidth = MeasureLabelWidth("LabelDropBones", 110);
            int lblDropDelta = lblDropWidth - 110;   // 右隣のコントロール群を同じ分だけ押し出す(dev#106 matsButtonと同じ手法)
            var lblDrop = new Label { Left = 8, Top = 48, Width = lblDropWidth, Text = T("LabelDropBones") };
            RegisterI18nText(lblDrop, "LabelDropBones");
            dropBonesBox = new TextBox { Left = 120 + lblDropDelta, Top = 44, Width = 400, Name = "dropBonesBox" };
            RegisterI18nTip(dropBonesBox, "TipDropBones");
            var lblDropHint = new Label { Left = 530 + lblDropDelta, Top = 48, Width = 190, Text = T("HintDropBonesEmpty") };
            RegisterI18nText(lblDropHint, "HintDropBonesEmpty");
            previewButton = new Button { Left = 730 + lblDropDelta, Top = 44, Width = 150, Height = 28, Text = T("BtnPreviewUpdate"), Name = "previewButton" };
            RegisterI18nText(previewButton, "BtnPreviewUpdate");
            previewButton.Click += delegate { RunPipeline(true, false, false); };
            RegisterI18nTip(previewButton, "TipPreviewButton");
            kodawariPanel.Controls.AddRange(new Control[] {
                lblShadow, shadowBar, shadowLabel, matsButton, matsHintLabel,
                lblDrop, dropBonesBox, lblDropHint, previewButton });

            // ---- プレビュー+ログ(こだわり設定の開閉で上端が動く) ----
            previewFront = new PictureBox { Left = 12, Width = 380, SizeMode = PictureBoxSizeMode.Zoom, BorderStyle = BorderStyle.FixedSingle };
            previewSide = new PictureBox { Left = 400, Width = 380, SizeMode = PictureBoxSizeMode.Zoom, BorderStyle = BorderStyle.FixedSingle };
            logBox = new TextBox
            {
                Left = 790, Width = 280,
                Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical,
                Font = ResolveLogFont()
            };

            // ---- 作成済みMODの一覧と適用/解除 ----
            var lblPaks = new Label { Left = 12, Top = 584, Width = 130, Text = T("LabelPakList") };
            RegisterI18nText(lblPaks, "LabelPakList");
            appliedLabel = new Label { Left = 150, Top = 584, Width = 920, Text = T("AppliedStatusChecking") };

            // 下カラムの右端は、上の appliedLabel(150+920)や logBox(790+280)と同じ
            // x=1070 に揃える。以前は一覧640+ボタン列(660〜840)で右に約230pxの
            // 死に地が残っていた(責任者指摘「下カラムの右側に不要な空白がある」)
            pakList = new ListView
            {
                Left = 12, Top = 608, Width = 870, Height = 180,
                View = View.Details, FullRowSelect = true, MultiSelect = false, HideSelection = false
            };
            // 列幅の合計(850)も一覧の幅に合わせて広げる。広げないと一覧の内側に空白が残る
            pakList.Columns.Add(T("ColAvatar"), 200);
            pakList.Columns.Add(T("ColFile"), 380);
            pakList.Columns.Add(T("ColSize"), 100);
            pakList.Columns.Add(T("ColCreatedAt"), 170);
            pakList.SelectedIndexChanged += delegate
            {
                if (pakList.SelectedItems.Count == 0) return;
                // 一覧から選ぶのも「今のアバターを切り替える」操作なので、
                // 走っているアバター読み込み(SetVrm)の結果は捨てる。
                // 捨てないと、後から届いた古い結果がこの選択を上書きしてしまう
                CancelAvatarLoad();
                string pak = (string)pakList.SelectedItems[0].Tag;
                string jd = Path.GetDirectoryName(Path.GetDirectoryName(pak));
                LoadPreviews(jd);
                RestoreSettings(Path.Combine(jd, "job.json"), true);
            };

            // ボタン列は一覧(右端882)の右隣から始め、右端を1070に揃える
            applyButton = new Button { Left = 890, Top = 608, Width = 180, Height = 34, Text = T("BtnApply"), Name = "applyButton" };
            RegisterI18nText(applyButton, "BtnApply");
            applyButton.Click += delegate { ApplySelected(); };
            removeButton = new Button { Left = 890, Top = 648, Width = 180, Height = 34, Text = T("BtnRemoveMod"), Name = "removeButton" };
            RegisterI18nText(removeButton, "BtnRemoveMod");
            removeButton.Click += delegate { RemoveApplied(); };
            var refreshButton = new Button { Left = 890, Top = 688, Width = 180, Height = 28, Text = T("BtnRefreshList") };
            RegisterI18nText(refreshButton, "BtnRefreshList");
            refreshButton.Click += delegate { RefreshPakList(); };
            // dev#106: BtnDeleteResult英語("Delete Conversion Result"24字)は幅180だと
            // あふれる。他ボタンと同じLeft=890で揃えるのをやめ、列の右端1070(=890+180、
            // このコメント直上の「右端を1070に揃える」方針)を保つ形で左へ広げる
            // (右端が固定なら、この行より上のUIには一切影響しない)
            int deleteButtonWidth = MeasureButtonWidth("BtnDeleteResult", 180);
            deleteButton = new Button { Left = 1070 - deleteButtonWidth, Top = 724, Width = deleteButtonWidth, Height = 28, Text = T("BtnDeleteResult"), Name = "deleteButton" };
            RegisterI18nText(deleteButton, "BtnDeleteResult");
            deleteButton.Click += delegate { DeleteSelected(); };
            // dev#25(オーナー裁定: メインUIのボタンは1つに統合)/dev#42(2026-07-29官能検査
            // 是正)/dev#42b(同日、再送対応): 旧「問い合わせ」「ログをコピー」ボタンを
            // 廃止し、この1ボタンに吸収。クリックで3段フローのダイアログ(ShowSupportDialog)
            // を開く: 説明→[問い合わせフォームを開く] → 編集可能な送信内容の確認→[OK]で送信
            // → 送信済み画面。送信済み後にログが変われば次回は確認画面から再開(再送=既存
            // スレッドへの追記。reportViewUrl/reportId/lastSentBaseLog参照)。
            // 手動コピーは引き続きこのダイアログ内の「ログを手動でコピー」で行える
            reportButton = new Button { Left = 890, Top = 760, Width = 180, Height = 28, Text = T("BtnReport"), Name = "reportButton" };
            RegisterI18nText(reportButton, "BtnReport");
            reportButton.Click += delegate { ShowSupportDialog(); };
            RegisterI18nTip(applyButton, "TipApply");
            RegisterI18nTip(removeButton, "TipRemove");
            RegisterI18nTip(deleteButton, "TipDelete");
            RegisterI18nTip(reportButton, "TipReport");

            // 一覧+適用ボタン列(Top=608〜788)のすぐ下に、その2つに関わる設定として置く。
            // 既定ONで「フル変換」「影のみ更新」どちらの完了後もこのままApplySelected()を呼ぶ
            // (実処理は既存の「Palworldに適用」ボタンと共通。OnPipelineDone参照)
            autoApplyCheck = new CheckBox
            {
                Left = 12, Top = 794, Width = 500, Height = 20,
                Text = T("CheckAutoApply"),
                Checked = LoadAutoApply(),
                Name = "autoApplyCheck"
            };
            RegisterI18nText(autoApplyCheck, "CheckAutoApply");
            autoApplyCheck.CheckedChanged += delegate { SaveAutoApply(); };
            RegisterI18nTip(autoApplyCheck, "TipAutoApply");

            // dev#15(更新通知のみ): 起動時チェックで新版が見つかった時だけ出す控えめな
            // クリック可能ラベル。既定は非表示(オフライン時・最新時は一切出さない)。
            // autoApplyCheck(Top=794, Height=20)のすぐ下、他コントロールと未重複の余白に置く
            updateLabel = new Label
            {
                Left = 12, Top = 822, Width = 1058, Height = 20,
                Text = "", Visible = false, AutoSize = false,
                Cursor = Cursors.Hand, ForeColor = Color.Blue, UseMnemonic = false
            };
            updateLabel.Click += delegate { OpenUpdateDownloadPage(); };
            RegisterI18nTip(updateLabel, "TipUpdateLabel");

            // dev#216 WP1: updateLabel(Top=822)の次の行に新設。FIX38(2026-07-31)で
            // ダウンロード・検証・展開の経路を削除し、updateLabelと同じく配布ページ
            // (OpenUpdateDownloadPage)を開くだけのボタンへ変更した(FIX25推奨案。
            // 適用エンジンがランチャー廃止で配布物から除去され、ダウンロードした内容を
            // 適用する者がいなくなったため)。表示条件もupdateLabelと揃え、
            // 新版検出時は常に表示する(以前のような「完全なエントリが取れた時だけ」
            // という絞り込みは、ダウンロードしない以上不要になった)。
            int updateNowWidth = MeasureButtonWidth("BtnUpdateNow", 130);
            updateNowButton = new Button
            {
                Left = 12, Top = 848, Width = updateNowWidth, Height = 22,
                Text = T("BtnUpdateNow"), Visible = false, Name = "updateNowButton"
            };
            RegisterI18nText(updateNowButton, "BtnUpdateNow");
            RegisterI18nTip(updateNowButton, "TipUpdateNow");
            updateNowButton.Click += delegate { OpenUpdateDownloadPage(); };

            // dev#173: 言語切替(小さなラベル+コンボボックス)。kodawariToggleと同じ行
            // (Top=88〜114)の右側、ボタン列と同じ右端1070に揃える。切替は即座に画面へ
            // 反映する(選択変更時にApplyLanguage()を呼ぶ。以前の「反映は次回起動時」
            // 仕様はdev#173で廃止)
            var lblLang = new Label { Left = 850, Top = 94, Width = 60, Text = T("LabelLanguage") };
            RegisterI18nText(lblLang, "LabelLanguage");
            langCombo = new ComboBox
            {
                Left = 914, Top = 90, Width = 156, Height = 24,
                DropDownStyle = ComboBoxStyle.DropDownList,
                Name = "langCombo"
            };
            // 言語名の自称(「日本語」「English」等)は各言語の話者が自分の言語を
            // 見分けるための固有名詞であり、UI言語に応じて訳し分けるものではないため
            // 翻訳テーブルを介さない(5言語とも常に同じ並びで出す)
            langCombo.Items.AddRange(new object[] { "日本語", "English", "한국어", "繁體中文", "简体中文" });
            langCombo.SelectedIndex = (int)Strings.Current;
            RegisterI18nTip(langCombo, "TipLanguageSwitch");
            langCombo.SelectedIndexChanged += delegate
            {
                // dev#173: 選択した瞬間に画面全体を新しい言語へ切り替える(ApplyLanguage、
                // 保存も内部で行う)。
                // dev#218: 確認MessageBox(「言語を切り替えました」)は、切替が即時反映に
                // なった(dev#173)ことで自明になったため廃止した。画面自体が選んだ言語へ
                // 変わるので、追加の案内は不要という2026-07-29ぱん指摘の裁定。
                Lang selectedLang = (Lang)langCombo.SelectedIndex;
                ApplyLanguage(selectedLang);
            };

            Controls.AddRange(new Control[] {
                lblVrm, vrmBox, browse, dropHint,
                convertButton, cancelButton, busyBar, statusLabel, blenderRetryButton,
                kodawariToggle, kodawariPanel, lblLang, langCombo,
                previewFront, previewSide, logBox,
                lblPaks, appliedLabel, pakList, applyButton, removeButton, refreshButton, deleteButton,
                reportButton, autoApplyCheck, updateLabel,
                updateNowButton });
            LayoutContentArea();

            // 押せない操作はボタン自体を無効化する(理由はステータス行に表示)
            vrmBox.TextChanged += delegate { UpdateButtonStates(); };
            dropBonesBox.TextChanged += delegate { UpdateButtonStates(); };
            pakList.SelectedIndexChanged += delegate { UpdateButtonStates(); };
            Shown += delegate
            {
                RefreshPakList();
                // 最後に開いていたVRMを復帰(設定・プレビューも一緒に戻る)
                try
                {
                    string f = LastVrmFile();
                    if (File.Exists(f))
                    {
                        string last = File.ReadAllText(f, Encoding.UTF8).Trim();
                        if (File.Exists(last)) SetVrm(last);
                    }
                }
                catch (Exception) { }
                // u54/dev#236: 配布物はBlender本体を同梱しない。無ければここで初回取得する
                // (バックグラウンド実行、UIはブロックしない)。WarmSharedCacheOnStartup()は
                // blenderReadyがtrueになった時点(DoEnsureBlenderReady側のPostToUi)で
                // 呼ぶよう移動した——ここで無条件に呼ぶと、まだ非同期チェック中で
                // blenderReadyが確定していない間は必ずno-opになってしまうため
                EnsureBlenderReadyOnStartup();
                UpdateButtonStates();
                CheckPalworldVersionOnce();   // 版が違えば警告のみ(ブロックしない)
                CheckOtherModsOnce();         // dev#103: 他MOD検出時も警告のみ(ブロックしない)
                CheckPathHealthOnStartup();   // dev#134(ぱん裁定でボタン案→自動診断へ転換): インストール/作業先パスの健全性
                CheckForUpdateOnStartup();    // dev#15: 更新通知(非同期・非ブロッキング、失敗は完全に無音)
                // FIX38(2026-07-31): dev#216 WP2で置いていた「起動確認シグナル」削除
                // (ClearVerifyPendingSignal)とTier2「前のバージョンに戻す」ボタンの表示
                // 切替(RefreshUpdateRevertButtonVisibility)は、どちらもランチャー側の
                // 適用エンジン(ランチャー廃止で配布物から除去済み)を前提にした処理で、
                // 適用エンジンが存在しない現在は何もしない不活性コードだった。除去した
                // (不活性経路は縮小する方針)
            };

            // ×で閉じる時: 変換が走っていたら確認してプロセスツリーごと中止する
            FormClosing += delegate(object s, FormClosingEventArgs e)
            {
                // dev#236: Blenderのバックグラウンド取得が進行中でも孤児化させない。
                // ユーザーには一切聞かない(モーダルの確認ボタンと違い、これは
                // ユーザーが明示的に始めた作業ではなく裏方の準備作業のため)。
                // 途中終了しても次回起動時のマーカー検証で自己修復される(PR #231踏襲)。
                KillBlenderSetupProcess();
                if (runningProc == null) return;
                var r = MessageBox.Show(
                    T("ConfirmExitWhileRunningBody"),
                    T("TitleConfirm"), MessageBoxButtons.YesNo);
                if (r == DialogResult.No) { e.Cancel = true; return; }
                KillConversion();
            };
        }

        ListView pakList;
        Label appliedLabel;
        ComboBox langCombo;   // dev#29/dev#173: 表示言語切替(settings_language.txtへ永続化、反映は即時)

        void LayoutContentArea()
        {
            int top = kodawariPanel.Visible ? 244 : 118;
            previewFront.Top = previewSide.Top = logBox.Top = top;
            previewFront.Height = previewSide.Height = logBox.Height = 570 - top;
        }

        void KillConversion()
        {
            var proc = runningProc;
            if (proc == null) return;
            try
            {
                // .NET Framework 4.8にはKill(entireProcessTree)が無いのでtaskkillで木ごと停止
                var psi = new ProcessStartInfo("taskkill", "/T /F /PID " + proc.Id)
                {
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                Process.Start(psi).WaitForExit(5000);
            }
            catch (Exception) { }
        }

        // dev#236: 旧BlenderSetupDialog.RequestCancel()相当。アプリ終了時に
        // ensure_blender.ps1のサブプロセスツリーを孤児化させないためだけに使う
        // (ユーザー起因のキャンセルUIは持たない、4.のFormClosingコメント参照)。
        void KillBlenderSetupProcess()
        {
            var proc = blenderSetupProc;
            if (proc == null) return;
            try
            {
                var psi = new ProcessStartInfo("taskkill", "/T /F /PID " + proc.Id)
                {
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                Process.Start(psi).WaitForExit(5000);
            }
            catch (Exception) { }
        }

        // ---------------- バックグラウンド作業の土台 ----------------
        // 方針: UIスレッドでは「ディスクを待つ処理」を一切しない。
        //   ・重いのは pak(数百MB)のSHA1と、job.json/プレビューPNGの読み込み
        //   ・結果の反映は必ず PostToUi 経由(Controlはこのスレッドからしか触れない)
        //   ・失敗は握りつぶさず backgroundError に残し、ステータス行とログに出す
        //     (ユーザーが次に画面を見た/操作した時点で必ず気づける)

        /// <summary>ワーカースレッドで実行する。例外はステータス行とログに出す。</summary>
        void RunBackground(string what, Action work)
        {
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                try { work(); }
                catch (Exception ex)
                {
                    PostToUi(delegate { SetBackgroundError(what, ex); UpdateButtonStates(); });
                }
            });
        }

        /// <summary>UIスレッドへ処理を戻す。フォームが既に閉じていればfalse。</summary>
        bool PostToUi(Action action)
        {
            try
            {
                if (IsDisposed || !IsHandleCreated) return false;
                BeginInvoke((Action)delegate
                {
                    try { action(); }
                    catch (Exception ex) { SetBackgroundError(T("WhatScreenUpdate"), ex); }
                });
                return true;
            }
            catch (Exception) { return false; }   // 閉じる途中などは何もしない
        }

        // UIスレッドから呼ぶこと
        void SetBackgroundError(string what, Exception ex)
        {
            backgroundError = TF("ErrFailedFormat", what, ex.Message);
            AppendLog("[エラー] " + backgroundError);
            statusLabel.Text = backgroundError;
        }

        // ---------------- VRM選択と設定の記憶・復元 ----------------

        void OnDragEnter(object sender, DragEventArgs e)
        {
            if (e.Data.GetDataPresent(DataFormats.FileDrop)) e.Effect = DragDropEffects.Copy;
        }

        void OnDragDrop(object sender, DragEventArgs e)
        {
            var files = (string[])e.Data.GetData(DataFormats.FileDrop);
            string path = files.Length > 0 ? files[0] : "";
            string f = path.ToLower();
            if (!(f.EndsWith(".vrm") || f.EndsWith(".fbx") || f.EndsWith(".prefab")))
            {
                MessageBox.Show(T("MsgDropVrmOrPrefab"));
                return;
            }
            bool isPrefab = f.EndsWith(".prefab");
            Action proceed = delegate
            {
                if (isPrefab) RunUnityExport(path);
                else SetVrm(path);
            };
            // dev#53/dev#236: Blender未セットアップ(初回取得の失敗/キャンセル含む)のまま
            // D&Dを受け付けると、後段(convert.ps1)がBlenderを探しに行って生のPowerShell
            // エラーで止まる。以前はここでYes/No確認モーダルを出して聞いていたが、初回
            // セットアップ中にポップアップを出さない裁定に伴い撤去した。ユーザーには
            // 聞かず自動でバックグラウンドのセットアップを進め、このファイルは
            // pendingBlenderReadyActionへ積んでおいて完了後に自動で続行する
            // (ユーザー操作はドロップ1回で済む)。
            if (!EnsureBlenderReadyForConversion(proceed)) return;
            proceed();
        }

        // dev#53/dev#236: blenderReadyがtrueならそのまま続行を許可(trueを返す)。
        // falseならモーダルで聞かず、バックグラウンドのセットアップを(未着手/失敗後の
        // 場合のみ)開始し、渡されたcontinuationをpendingBlenderReadyActionへ積んで
        // falseを返す。continuationはセットアップが成功した時点で自動的に実行される
        // (DoEnsureBlenderReady参照)。呼び出し元はfalseの間は何もしなくてよい
        // (常設UIのstatusLabelが「準備中」を示し続ける)。
        bool EnsureBlenderReadyForConversion(Action continuation)
        {
            if (blenderReady) return true;
            pendingBlenderReadyAction = continuation;
            EnsureBlenderReadyOnStartup();
            UpdateButtonStates();
            return false;
        }

        void BrowseVrm()
        {
            using (var dlg = new OpenFileDialog { Filter = T("FileFilterAvatar") })
            {
                if (dlg.ShowDialog() == DialogResult.OK) SetVrm(dlg.FileName);
            }
        }

        bool HasHumanoidJson(string fbxPath)
        {
            string stem = Path.Combine(Path.GetDirectoryName(fbxPath),
                Path.GetFileNameWithoutExtension(fbxPath));
            return File.Exists(stem + ".humanoid.json")
                || File.Exists(Path.Combine(Path.GetDirectoryName(fbxPath), "humanoid.json"));
        }

        string LastVrmFile() { return Path.Combine(appRoot, "settings_lastvrm.txt"); }

        // 「自動で適用」チェックの記憶場所。アバターごとの設定(job.json)ではなく、
        // settings_paksdir.txt と同じ「GUI側のグローバル設定」の
        // 流儀に合わせる(このチェックはアバターの変換パラメータではなく、
        // GUIの動作モードなので、アバターを跨いで1つ覚えていれば十分)
        string AutoApplyFile() { return Path.Combine(appRoot, "settings_autoapply.txt"); }

        bool LoadAutoApply()
        {
            try
            {
                string f = AutoApplyFile();
                if (File.Exists(f))
                    return File.ReadAllText(f, Encoding.UTF8).Trim() != "false";
            }
            catch (Exception) { }
            return true;   // 既定ON
        }

        void SaveAutoApply()
        {
            try { File.WriteAllText(AutoApplyFile(), autoApplyCheck.Checked ? "true" : "false", new UTF8Encoding(false)); }
            catch (Exception) { }
        }

        // SetVrmがバックグラウンドで集める材料。ワーカースレッドはここへ詰めるだけで、
        // Control(vrmBox等)には絶対に触らない
        class AvatarLoad
        {
            public string Path;
            public string JobDir;
            public string JobText;          // job.jsonの中身(無い/読めない時はnull)
            public Image Front;             // プレビュー(無ければnull)
            public Image Side;
            public bool NeedHumanoidJson;   // FBXなのにボーン対応表が無い
        }

        // アバターを取り込む。ディスク待ち(job.json・プレビューPNGの読み込み、
        // 「最後に開いたVRM」の保存)はワーカースレッドへ出すので、この呼び出し自体は
        // すぐ返る。ドロップ元のエクスプローラも画面も固まらない。
        // 反映の順序・内容は従来と同一で、変わるのは「いつ返るか」だけ。
        // newSession: 2026-07-26 LX追加。true(既定)なら「ユーザーが新しいアバターを
        // 選び直した」とみなしてセッションログ(sessionLog)をリセットする。
        // OnUnityExportDoneからの呼び出し(Unity輸出の続き)だけはfalseを渡し、
        // 直前に積んだUnity輸出の記録を消さずに変換工程を同じセッションへ積み増す。
        void SetVrm(string path, bool newSession = true)
        {
            if (newSession) sessionLog.Clear();
            vrmBox.Text = path;
            licenseConfirmed = false;
            backgroundError = null;
            // 同じアバターを前に触っていたら、その時の設定を復元する(規約確認の記憶含む)
            string jobJson = Path.Combine(workRoot, SanitizeName(
                Path.GetFileNameWithoutExtension(path)), "job.json");
            int gen = ++avatarLoadGen;   // これより古い読み込みの結果は捨てられる
            avatarLoading = true;
            UpdateButtonStates();
            RunBackground(T("WhatAvatarLoad"), delegate
            {
                AvatarLoad loaded;
                try { loaded = ReadAvatarFiles(path, jobJson); }
                catch (Exception ex)
                {
                    PostToUi(delegate
                    {
                        if (gen != avatarLoadGen) return;
                        avatarLoading = false;
                        SetBackgroundError(T("WhatAvatarLoad"), ex);
                        UpdateButtonStates();
                    });
                    return;
                }
                bool posted = PostToUi(delegate
                {
                    // 読んでいる間に別のアバターへ切り替わっていたら、この結果は捨てる
                    // (古い結果が新しい選択を上書きする事故の防止)
                    if (gen != avatarLoadGen) { DisposeLoad(loaded); return; }
                    ApplyAvatarLoad(loaded);
                });
                if (!posted) DisposeLoad(loaded);
            });
        }

        // ワーカースレッド側。Controlに触らないこと
        AvatarLoad ReadAvatarFiles(string path, string jobJson)
        {
            var r = new AvatarLoad { Path = path, JobDir = Path.GetDirectoryName(jobJson) };
            // FBX入力はボーン対応表(humanoid.json)が必要
            r.NeedHumanoidJson = path.ToLower().EndsWith(".fbx") && !HasHumanoidJson(path);
            if (File.Exists(jobJson))
            {
                // 読めない場合は従来のRestoreSettingsと同じく「復元しない」で進む
                try { r.JobText = File.ReadAllText(jobJson, Encoding.UTF8); }
                catch (Exception) { r.JobText = null; }
            }
            // サムネイルは他の処理を待たせず、読めた時点で出す。
            // (従来もjob.jsonが在る時だけ読んでいた。無い時に前のアバターの絵が
            //  残るのは従来どおりの挙動)
            if (r.JobText != null)
            {
                r.Front = TryLoadImage(Path.Combine(r.JobDir, "converted", "preview_male_stand.png"));
                r.Side = TryLoadImage(Path.Combine(r.JobDir, "converted", "preview_male_stand_side.png"));
            }
            return r;
        }

        // UIスレッド側。従来のSetVrmの「反映」部分をそのままの順序で行う
        void ApplyAvatarLoad(AvatarLoad r)
        {
            avatarLoading = false;
            // 読み込みを始めた時のアバターと、今画面にあるアバターが同じかを確認する。
            // 世代番号で拾えない経路(アバター欄への直接入力)への最後の砦。
            // 違っていれば何も反映しない(古い内容で新しい選択を上書きしない)
            if (vrmBox.Text != r.Path) { DisposeLoad(r); UpdateButtonStates(); return; }
            // 次回起動時に自動で開く。書くのはUIスレッド(数十バイト)。
            // 裏で書くと、続けて2体入れられた時に書き込み順が逆転しうる
            try { File.WriteAllText(LastVrmFile(), r.Path, new UTF8Encoding(false)); }
            catch (Exception) { }
            if (r.JobText != null)
                ApplyRestoredSettings(r.JobText, r.JobDir, false, true, r.Front, r.Side);
            if (r.NeedHumanoidJson)
            {
                MessageBox.Show(T("MsgHumanoidJsonNeededBody"), T("TitleHumanoidJsonNeeded"));
                UpdateButtonStates();
                return;
            }
            // プレビューが未生成(or設定が変わって古い)なら、その場で自動生成する。
            // dev#53: blenderReadyがfalse(初回セットアップ未完了)のままRunPipelineへ
            // 入ると、convert.ps1側がBlenderを探しに行って生のエラーで止まる。
            // ここではRunPipelineを呼ばずに見送るだけにとどめ、案内は
            // UpdateButtonStates()側の既存表示(blenderSetupMessage、1408行目付近)に譲る。
            if (File.Exists(r.Path) && !IsPreviewFresh() && runningProc == null && blenderReady)
                RunPipeline(true, false, true);
            UpdateButtonStates();
        }

        // 新しいユーザー操作が始まった: 走っているアバター読み込みの結果は捨てる
        void CancelAvatarLoad()
        {
            avatarLoadGen++;
            avatarLoading = false;
        }

        void DisposeLoad(AvatarLoad r)
        {
            if (r == null) return;
            try { if (r.Front != null) r.Front.Dispose(); } catch (Exception) { }
            try { if (r.Side != null) r.Side.Dispose(); } catch (Exception) { }
        }

        Image TryLoadImage(string path)
        {
            try { return File.Exists(path) ? LoadImageNoLock(path) : null; }
            catch (Exception) { return null; }
        }

        void RestoreSettings(string jobJson, bool setVrmPath)
        {
            if (!File.Exists(jobJson)) return;
            string json;
            try { json = File.ReadAllText(jobJson, Encoding.UTF8); }
            catch (Exception) { return; }
            ApplyRestoredSettings(json, Path.GetDirectoryName(jobJson), setVrmPath, false, null, null);
        }

        // job.jsonの中身を画面へ反映する(UIスレッド専用)。
        // imagesReady=true なら、既にバックグラウンドで読み終えたプレビュー画像を使う
        // (=ここでディスクを待たない)。false なら従来どおりこの場で読む
        void ApplyRestoredSettings(string json, string jobDir, bool setVrmPath,
                                   bool imagesReady, Image front, Image side)
        {
            try
            {
                if (setVrmPath)
                {
                    string vrm = JsonStr(json, "vrm_path");
                    if (vrm != null) vrmBox.Text = vrm;
                }
                double sh = JsonNum(json, "shoulder_offset_deg", shoulderBar.Value);
                shoulderBar.Value = Math.Max(shoulderBar.Minimum,
                    Math.Min(shoulderBar.Maximum, (int)Math.Round(sh)));
                double lift = JsonNum(json, "shadow_lift", -1);
                if (lift >= 0)
                    shadowBar.Value = Math.Max(0, Math.Min(100, (int)Math.Round(100 - lift * 100)));
                mergeFingersCheck.Checked = JsonBool(json, "merge_fingers", mergeFingersCheck.Checked);
                unlitCheck.Checked = JsonBool(json, "unlit", unlitCheck.Checked);
                twoSidedCheck.Checked = JsonBool(json, "force_two_sided", twoSidedCheck.Checked);
                licenseConfirmed = JsonBool(json, "license_confirmed", false);
                var drops = JsonStrArray(json, "drop_bones");
                if (drops != null) dropBonesBox.Text = string.Join(", ", drops.ToArray());
                if (imagesReady)
                {
                    if (front != null) previewFront.Image = front;
                    if (side != null) previewSide.Image = side;
                }
                else LoadPreviews(jobDir);
            }
            catch (Exception) { }
        }

        // --- 最小限のJSON読み取り(自前生成のjob.json限定なのでregexで足りる) ---
        // dev#87/#89/#91(wp878991): known_good_palworld.json/versions.jsonの読み取りでも
        // 再利用するためstaticにした(挙動は不変。`this`を参照していなかったため安全)。
        // PalworldCompat.cs的な独立クラスに切り出すのが理想だが、build_app.ps1が
        // DiveToPalworld.cs単一ファイルしかコンパイルしないため、同一ファイル内に留める。
        internal static string JsonStr(string json, string key)
        {
            var m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
            if (!m.Success) return null;
            return m.Groups[1].Value.Replace("\\\\", "\\").Replace("\\\"", "\"");
        }

        internal static double JsonNum(string json, string key, double def)
        {
            var m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*(-?[0-9.]+)");
            if (!m.Success) return def;
            double v;
            return double.TryParse(m.Groups[1].Value, NumberStyles.Float,
                CultureInfo.InvariantCulture, out v) ? v : def;
        }

        internal static bool JsonBool(string json, string key, bool def)
        {
            var m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*(true|false)");
            return m.Success ? m.Groups[1].Value == "true" : def;
        }

        internal static List<string> JsonStrArray(string json, string key)
        {
            var m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*\\[([^\\]]*)\\]");
            if (!m.Success) return null;
            var result = new List<string>();
            foreach (Match s in Regex.Matches(m.Groups[1].Value, "\"((?:[^\"\\\\]|\\\\.)*)\""))
                result.Add(s.Groups[1].Value.Replace("\\\\", "\\").Replace("\\\"", "\""));
            return result;
        }

        /// <summary>"key": { ... } の値部分を波括弧の深さを数えてバランス良く取り出す。
        /// JsonStr等の単純な正規表現ヘルパーでは、ネストしたオブジェクトの中に更に
        /// "}"を含む配列要素(known_versionsの各要素オブジェクト等)があると取りこぼす
        /// ため、dev#89のversions.json補助フィールド("palworld_known_good")用に追加した。
        /// 文字列リテラル内の"{"/"}"は考慮しない(この用途では自前生成JSONのみを
        /// 対象にするため、簡略化で十分)。閉じ括弧が見つからない/キーが無ければnull。</summary>
        internal static string JsonObj(string json, string key)
        {
            if (string.IsNullOrEmpty(json)) return null;
            var m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*\\{");
            if (!m.Success) return null;
            int start = m.Index + m.Length - 1;   // 開き'{'の位置
            int depth = 0;
            for (int i = start; i < json.Length; i++)
            {
                if (json[i] == '{') depth++;
                else if (json[i] == '}')
                {
                    depth--;
                    if (depth == 0) return json.Substring(start, i - start + 1);
                }
            }
            return null;
        }

        // FIX38(2026-07-31): JsonArrItemByField(dev#216、versions.jsonの"versions"配列
        // から特定バージョンのエントリを引くヘルパー)は、アプリ内自己更新ダウンロード
        // 経路の削除に伴い唯一の呼び出し元(CheckForUpdateOnStartup)を失ったため、
        // ヘルパー自体も削除した(不活性コードを増やさない)。

        // ---------------- job.json生成 ----------------

        string SanitizeName(string s)
        {
            var sb = new StringBuilder();
            foreach (char c in s)
                if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))
                    sb.Append(c);
            if (sb.Length == 0) sb.Append("Avatar");
            return sb.ToString();
        }

        string J(string s) { return s.Replace("\\", "\\\\"); }

        // U44: 配布zipのルート簡素化でthird_party\/tools\をassets\配下へ集約した。
        // 開発チェックアウト(リポジトリ直下にthird_party\/tools\がある)では
        // 従来どおり直下を見るフォールバックにして、開発実行・配布zip実行の
        // どちらでも動くようにする(pipeline\/research\/unity\は他コード
        // (テストハーネス・export_from_unity.ps1・pipeline\pyのREPO_DIR相対解決)
        // が直下前提で固定のため移動していない。詳細はdocs\REPORT_U44_2026-07-25.md)
        string AssetSubDir(string name)
        {
            string dist = Path.Combine(appRoot, "assets", name);
            if (Directory.Exists(dist)) return dist;
            return Path.Combine(appRoot, name);
        }

        string JsonNameList(string commaSeparated)
        {
            var items = new List<string>();
            foreach (string raw in commaSeparated.Split(','))
            {
                string t = raw.Trim();
                if (t.Length > 0)
                    items.Add("\"" + t.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"");
            }
            return string.Join(", ", items.ToArray());
        }

        string WriteJob()
        {
            string vrm = vrmBox.Text.Trim();
            string name = SanitizeName(Path.GetFileNameWithoutExtension(vrm));
            string jobDir = Path.Combine(workRoot, name);
            Directory.CreateDirectory(jobDir);
            string blender = FindBlender();
            string addonZip = FindFirst(AssetSubDir("third_party"), "VRM_Addon_for_Blender-Extension*.zip");

            var sb = new StringBuilder();
            sb.Append("{\n");
            sb.AppendFormat("  \"vrm_path\": \"{0}\",\n", J(vrm));
            sb.AppendFormat("  \"avatar_name\": \"{0}\",\n", name);
            sb.AppendFormat("  \"shoulder_offset_deg\": {0},\n", shoulderBar.Value);
            sb.AppendFormat("  \"merge_fingers\": {0},\n", mergeFingersCheck.Checked ? "true" : "false");
            sb.AppendFormat("  \"unlit\": {0},\n", unlitCheck.Checked ? "true" : "false");
            sb.AppendFormat("  \"force_two_sided\": {0},\n", twoSidedCheck.Checked ? "true" : "false");
            sb.AppendFormat(CultureInfo.InvariantCulture,
                "  \"shadow_lift\": {0:0.###},\n", (100 - shadowBar.Value) / 100.0);
            sb.AppendFormat("  \"drop_bones\": [{0}],\n", JsonNameList(dropBonesBox.Text));
            sb.AppendFormat("  \"license_confirmed\": {0},\n", licenseConfirmed ? "true" : "false");
            sb.Append("  \"paths\": {\n");
            sb.AppendFormat("    \"blender_exe\": \"{0}\",\n", J(blender));
            // WP16(公開issue #8): 「Palworldに適用」で使うPaksフォルダの解決結果
            // (レジストリ/vdf自動探索+ダイアログ済み)を、バニラ抽出用の
            // paths.palworld_pakにもそのまま流用する。従来はこの配線が無く、
            // GUIが解決できてもextract_vanilla.py側は決め打ちの既定パスしか
            // 見ていなかった(=変換前に失敗する不具合の直接原因)。
            // PaksDir()は自動探索/ダイアログにより時間がかかることがあるため
            // ここではダイアログを出さないPaksDirQuiet()を使う(WriteJob()は
            // 変換開始のたびに呼ばれるため、毎回ダイアログを出すのは不適切。
            // 未解決ならpaths.palworld_pakを省略し、pipeline\py側の
            // palworld_locate.pyによる既定探索+明確なエラーに委ねる)。
            string paksDirForJob = PaksDirQuiet();
            string palworldPakLine = null;
            if (paksDirForJob != null)
            {
                string palworldPak = Path.Combine(paksDirForJob, PalWindowsPakName);
                palworldPakLine = string.Format("    \"palworld_pak\": \"{0}\"\n", J(palworldPak));
            }
            sb.AppendFormat("    \"vrm_addon_zip\": \"{0}\"{1}\n", J(addonZip), palworldPakLine != null ? "," : "");
            if (palworldPakLine != null) sb.Append(palworldPakLine);
            sb.Append("  }\n}\n");
            string jobJson = Path.Combine(jobDir, "job.json");
            File.WriteAllText(jobJson, sb.ToString(), new UTF8Encoding(false));
            return jobJson;
        }

        // WP11(2026-07-27追加): convert.ps1の起動先パス解決・引数組み立てを、実行
        // (RunPipeline)とヘッドレス配線契約検査(--emit-wiring起動、EmitWiring参照)の
        // 両方から同じメソッドで呼べるよう切り出した。ロジック自体はRunPipelineに
        // 元々あったものをそのまま移しただけで、戻り値・動作は変えていない
        // (tests\shipcheck\gui_wiring_check.py がこの2メソッドの結果を検査する)。
        string BuildConvertScriptPath()
        {
            return Path.Combine(appRoot, "pipeline", "cli", "convert.ps1");
        }

        string BuildConvertArgs(string script, string jobJson, bool previewOnly, bool materialsOnly)
        {
            return string.Format("-NoProfile -ExecutionPolicy Bypass -File \"{0}\" -Job \"{1}\"{2}{3}",
                script, jobJson, previewOnly ? " -PreviewOnly" : "",
                materialsOnly ? " -MaterialsOnly" : "");
        }

        string FindBlender()
        {
            string[] candidates = {
                FindFirst(AssetSubDir("tools"), "blender-*-windows-x64"),
                @"C:\P\Work\PalMod\tools\blender-4.3.2-windows-x64"
            };
            foreach (string c in candidates)
            {
                if (c != null && File.Exists(Path.Combine(c, "blender.exe")))
                {
                    // dev#149対策: 実体(c)はそのまま(手動配置案内・監査ツールが
                    // 前提にしている場所を変えない)。深いインストール先
                    // (KonoAsset管理下等)ではここから先(\4.3\python\Lib\
                    // site-packages\numpy\_core\...)がWindowsのMAX_PATH(260文字)
                    // へ接近/超過し、Blender同梱numpyのDLLロードが失敗する
                    // (LoadLibraryExWへ渡す文字列そのものが長すぎるため)。
                    // 短いNTFSジャンクション経由の別名を用意し、以後はそちらを
                    // 返す(ジャンクション作成に失敗しても実体パスへ安全に
                    // フォールバックするので、既存挙動を壊すことはない)。
                    string shortExe = TryGetShortBlenderPath(c);
                    return shortExe ?? Path.Combine(c, "blender.exe");
                }
            }
            return "blender.exe";
        }

        string FindFirst(string dir, string pattern)
        {
            if (!Directory.Exists(dir)) return null;
            var hits = Directory.GetFileSystemEntries(dir, pattern);
            return hits.Length > 0 ? hits[0] : null;
        }

        // dev#149(MAX_PATH超過でnumpy DLL読込失敗)対策。
        //
        // 背景: 配布物の実体パスは <AppRoot>\assets\tools\blender-4.3.2-windows-x64\
        // 以下と固定的に深い(4.3\python\Lib\site-packages\numpy\_core\
        // _multiarray_umath.cp311-win_amd64.pyd まで足すと単体で150文字超)。
        // これ自体は他の監査・手動配置案内(ensure_blender.ps1の
        // Show-D2PFailureGuidance)が前提にしている場所なので動かさない。
        // 代わりに %LOCALAPPDATA%\Uchinoko\blender_link\<hash> という短い
        // NTFSディレクトリジャンクション(管理者権限不要。symlinkと異なりUACの
        // 対象外)を経由させ、Blenderへ実際に渡すパス文字列自体を短くする。
        //
        // ジャンクションは実体を一切コピーしない別名(エイリアス)なので、
        // ・実体の更新(Blenderの再取得・パッチ差し替え)はジャンクション越しでも
        //   即座に反映される(同一ファイルを指しているだけのため)
        // ・既存インストール(このパッチ適用前に既にBlenderを取得済みの環境)でも、
        //   次回起動時にFindBlender()が呼ばれた時点で自動的にジャンクションが
        //   作られる(ユーザー操作・移行手順は不要)
        // ・ジャンクション作成に失敗する環境(権限・ファイルシステムの制約等)でも
        //   shortExeがnullを返すだけで、呼び出し元は深い実体パスへフォールバック
        //   する(=このパッチ適用前と同じ、常に動く状態を維持する)
        string TryGetShortBlenderPath(string deepBlenderDir)
        {
            try
            {
                string deepExe = Path.Combine(deepBlenderDir, "blender.exe");
                if (!File.Exists(deepExe)) return null;

                string hash = ShortHash(deepBlenderDir.ToLowerInvariant());
                string linkDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Uchinoko", "blender_link", hash);
                string linkExe = Path.Combine(linkDir, "blender.exe");

                if (IsShortBlenderExeValid(linkExe, deepExe)) return linkExe;
                if (!EnsureBlenderJunction(linkDir, deepBlenderDir)) return null;
                return IsShortBlenderExeValid(linkExe, deepExe) ? linkExe : null;
            }
            catch (Exception) { return null; }
        }

        // ジャンクション越しに見えているblender.exeが、意図した実体(deepExe)と
        // 同一かどうかの簡易確認。.NET Framework 4.8には標準でリパースポイントの
        // ターゲットを直接読むAPIが無いため、サイズ+更新日時の一致で代替する
        // (別実体が偶然この2値まで一致する確率は無視できるほど低い)。
        bool IsShortBlenderExeValid(string linkExe, string deepExe)
        {
            try
            {
                if (!File.Exists(linkExe)) return false;
                var a = new FileInfo(linkExe);
                var b = new FileInfo(deepExe);
                return a.Length == b.Length && a.LastWriteTimeUtc == b.LastWriteTimeUtc;
            }
            catch (Exception) { return false; }
        }

        // ジャンクション(mklink /J相当)を作成する。既存のlinkDirが
        // (a) 存在しない -> そのまま作成
        // (b) リパースポイントだが古いターゲットを指す(IsShortBlenderExeValidが
        //     falseだった、= 呼び出し元がここに来た理由) -> 張り直す
        // (c) 万一リパースポイントではない実フォルダが衝突している -> 触らずあきらめる
        //     (Directory.Delete非再帰は空フォルダしか消せないので、中身があれば
        //     例外→catchでfalseになり安全にフォールバックする。中身が空でも
        //     「弊ツール管理外の何か」の可能性が捨てきれないため、リパース
        //     ポイントでないと分かった時点で明示的に手を引く)
        bool EnsureBlenderJunction(string linkDir, string targetDir)
        {
            try
            {
                string parent = Path.GetDirectoryName(linkDir);
                if (parent != null) Directory.CreateDirectory(parent);

                if (Directory.Exists(linkDir))
                {
                    bool isReparse = (File.GetAttributes(linkDir) & FileAttributes.ReparsePoint) != 0;
                    if (!isReparse) return false;
                    // 非再帰削除: リパースポイント自体だけが外れる。ターゲット側
                    // (実体のBlenderフォルダ)の中身には一切影響しない
                    Directory.Delete(linkDir, false);
                }

                var psi = new ProcessStartInfo("cmd.exe",
                    string.Format("/c mklink /J \"{0}\" \"{1}\"", linkDir, targetDir))
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                using (var p = Process.Start(psi))
                {
                    p.WaitForExit(10000);
                    return p.ExitCode == 0 && Directory.Exists(linkDir);
                }
            }
            catch (Exception) { return false; }
        }

        string ShortHash(string s)
        {
            using (var sha1 = SHA1.Create())
            {
                byte[] h = sha1.ComputeHash(Encoding.UTF8.GetBytes(s));
                var sb = new StringBuilder();
                for (int i = 0; i < 4; i++) sb.Append(h[i].ToString("x2"));
                return sb.ToString();
            }
        }

        // u54(2026-07-27): 配布物はBlender本体を同梱しない(BOOTH容量・ビルド時間の
        // 主因だったBlenderポータブル989MBを外した)。FindBlender()の結果が実在
        // しなければ、ここで pipeline\cli\ensure_blender.ps1(公式サイトからの
        // 初回取得+従来make_dist.ps1がビルド時にやっていた差し込み処理と同内容)を
        // バックグラウンドで実行する。起動時(Shown)と
        // 「Blenderを再取得」ボタン(blenderRetryButton)の両方から呼ぶ。
        //
        // dev#236(2026-07-30、オーナー裁定): 以前はここでモーダルダイアログ
        // (BlenderSetupDialog)を出してUIスレッドをブロックしていたが、初回セットアップ
        // (Blender等の取得)は起動時バックグラウンドで実行し、ポップアップ・モーダルを
        // 出してはならないという裁定に伴い撤去した。このメソッド自体はUIスレッドから
        // 呼ばれるが、即座にRunBackground()でワーカースレッドへ処理を投げて戻る
        // (ブロックしない)。実際の判定・取得ロジックはDoEnsureBlenderReady()に移した。
        // 二重起動防止: 既に実行中(blenderSetupRunning)なら何もしない。
        //
        // dev#230対策(踏襲): 以前はここで「exeが実在するか」だけを見て即readyにしていた
        // ため、ensure_blender.ps1のマーカー検証(Test-D2PMarkerValid: version/sha256/
        // patched一致)が「exeが既に存在する」場合には一度も呼ばれなかった。修正は
        // DoEnsureBlenderReady()側にそのまま引き継いである(判定ロジックはensure_blender.ps1
        // 側に一元化、ここでTest-D2PMarkerValid相当を重複実装しない)。
        void EnsureBlenderReadyOnStartup()
        {
            if (blenderSetupRunning || blenderReady) return;
            blenderSetupRunning = true;
            blenderSetupMessage = T("StatusBlenderChecking");
            UpdateButtonStates();
            RunBackground(T("WhatBlenderSetup"), DoEnsureBlenderReady);
        }

        // dev#236: DoEnsureBlenderReady()の分岐をファイルI/O・プロセス起動から切り離し、
        // 3つのbool入力だけで判定する純関数(--check-blender-setup-decisionで
        // ヘッドレスに全8通りを検査できる。既存のDetectLangFromCulture()と同じ狙い)。
        // 実際のマーカー有効性判定自体はensure_blender.ps1のTest-D2PMarkerValidに
        // 一元化されたまま(ここではその「結果」を受け取るだけで重複実装しない)。
        internal enum BlenderSetupAction
        {
            ReadyNoAction,        // 既にBlenderが使える。何もしなくてよい
            NeedFullSetup,        // ensure_blender.ps1のフル実行(取得/再パッチ)が必要
            DevNotFoundNoScript   // 開発チェックアウト等でensurePs1自体が無く、exeも無い
        }

        internal static BlenderSetupAction DecideBlenderSetupAction(
            bool ensurePs1Exists, bool blenderExeExists, bool checkOnlyValid)
        {
            if (!ensurePs1Exists)
            {
                // 取得スクリプト自体が無い(想定外の構成)。マーカー検証もできないため、
                // 旧来どおりexe実在だけで判定する(checkOnlyValidはこの分岐では無関係)。
                return blenderExeExists ? BlenderSetupAction.ReadyNoAction : BlenderSetupAction.DevNotFoundNoScript;
            }
            if (blenderExeExists && checkOnlyValid) return BlenderSetupAction.ReadyNoAction;
            return BlenderSetupAction.NeedFullSetup;
        }

        // dev#236: ワーカースレッドで実行する実処理(UIを一切直接触らない。反映は
        // PostToUi経由)。結果に応じてblenderReady/blenderSetupMessageを更新し、
        // ボタン状態を再計算する。成功していてD&D等からの継続処理
        // (pendingBlenderReadyAction)が積まれていれば、そのままここで実行する
        // (ユーザーに再操作を求めない)。
        void DoEnsureBlenderReady()
        {
            string blender = FindBlender();
            string ensurePs1 = Path.Combine(appRoot, "pipeline", "cli", "ensure_blender.ps1");
            bool ensurePs1Exists = File.Exists(ensurePs1);
            bool blenderExeExists = File.Exists(blender);
            // -CheckOnlyはensurePs1が無ければ意味を持たない(呼び出し不能)ので、
            // 存在する場合のみ評価する(遅延評価。DecideBlenderSetupActionは
            // その結果bool一つだけを受け取る純関数)
            bool checkOnlyValid = ensurePs1Exists && blenderExeExists && RunEnsureBlenderCheckOnly(ensurePs1);

            BlenderSetupAction action = DecideBlenderSetupAction(ensurePs1Exists, blenderExeExists, checkOnlyValid);

            bool ok;
            string failMessage = null;
            switch (action)
            {
                case BlenderSetupAction.ReadyNoAction:
                    ok = true;
                    break;
                case BlenderSetupAction.DevNotFoundNoScript:
                    ok = false;
                    failMessage = TF("MsgBlenderNotFoundDevFormat", blender);
                    break;
                default: // NeedFullSetup
                    ok = RunEnsureBlenderSetupProcess(ensurePs1, out failMessage);
                    break;
            }

            PostToUi(delegate
            {
                blenderSetupRunning = false;
                blenderReady = ok;
                blenderSetupMessage = ok ? null
                    : (string.IsNullOrEmpty(failMessage) ? T("MsgBlenderSetupFailedShort") : failMessage);
                UpdateButtonStates();
                if (ok)
                {
                    // U54 WP-B: Blenderが使える状態になった時点でバニラ準備+
                    // ライブテンプレートの事前計算を静かに開始する(旧実装ではShownの
                    // 最後で無条件に呼んでいたが、EnsureBlenderReadyOnStartup()の
                    // 非同期化に伴いここへ移した——そうしないと「まだ確認中」の間に
                    // blenderReady==falseで毎回no-opになってしまうため)
                    WarmSharedCacheOnStartup();
                    // dev#288 WP(prewarm): Blender本体プロセスのOSディスクキャッシュ
                    // ウォームも同じタイミングで撃つ。ただしpendingBlenderReadyAction
                    // (D&D等で保留されていた変換がこの直後に始まる)がある場合は
                    // 「変換中は実行しない」を満たすため撃たない(実変換のstep01が
                    // 最良のプリウォームそのものになるので、二重に撃つ意味も無い)。
                    if (pendingBlenderReadyAction == null)
                    {
                        WarmBlenderProcessOnStartup();
                    }
                }
                if (ok && pendingBlenderReadyAction != null)
                {
                    Action a = pendingBlenderReadyAction;
                    pendingBlenderReadyAction = null;
                    a();
                }
            });
        }

        // dev#236: 旧BlenderSetupDialog.StartProcess()相当。ensure_blender.ps1の
        // フル実行(取得/再パッチ)をワーカースレッド上で同期的に行う(このスレッド自体が
        // 既にUIから切り離されているので、ここでWaitForExit()してよい)。stdoutの
        // ##PROGRESS##行(旧ダイアログと同じ正規表現ProgressMarkを再利用)を
        // busyBar/statusLabelへ反映する。キャンセルUIは持たない(モーダルではないので
        // ユーザーの操作を妨げておらず、緊急に止める理由がないため。アプリを閉じた
        // 場合はFormClosingでプロセスツリーごと止める)。
        bool RunEnsureBlenderSetupProcess(string ensurePs1, out string failMessage)
        {
            failMessage = null;
            var allOutput = new StringBuilder();
            try
            {
                string args = string.Format(
                    "-NoProfile -ExecutionPolicy Bypass -File \"{0}\" -AppRoot \"{1}\"",
                    ensurePs1, appRoot);
                var psi = new ProcessStartInfo(FindPwsh(), args)
                {
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8
                };
                var proc = new Process { StartInfo = psi };
                DataReceivedEventHandler onData = delegate(object s, DataReceivedEventArgs e)
                {
                    if (e.Data == null) return;
                    lock (allOutput) { allOutput.AppendLine(e.Data); }
                    Match m = ProgressMark.Match(e.Data);
                    if (!m.Success) return;
                    int pct;
                    if (!int.TryParse(m.Groups[1].Value, out pct)) return;
                    pct = Math.Max(0, Math.Min(100, pct));
                    string phase = m.Groups[2].Value.Trim();
                    string text = TF("StatusBlenderSettingUpFormat", phase, pct);
                    PostToUi(delegate
                    {
                        blenderSetupMessage = text;
                        busyBar.Visible = true;
                        busyBar.Value = pct;
                        statusLabel.Text = text;
                    });
                };
                proc.OutputDataReceived += onData;
                proc.ErrorDataReceived += onData;
                blenderSetupProc = proc;
                proc.Start();
                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();
                proc.WaitForExit();
                blenderSetupProc = null;

                string text2;
                lock (allOutput) { text2 = allOutput.ToString(); }
                if (proc.ExitCode == 0) return true;

                // [D2P_BLENDER_SETUP_FAIL]以降の案内文だけを抜き出す(先頭のPROGRESS行は不要)
                int idx = text2.IndexOf("[D2P_BLENDER_SETUP_FAIL]");
                failMessage = idx >= 0 ? text2.Substring(idx).Trim() : text2.Trim();
                return false;
            }
            catch (Exception ex)
            {
                blenderSetupProc = null;
                failMessage = TF("ErrBlenderSetupStartFailedFormat", ex.Message);
                return false;
            }
        }

        // dev#230: ensure_blender.ps1 -CheckOnly を同期・非表示で実行し、
        // Test-D2PMarkerValid(exe実在+マーカー実在+version/sha256/patched一致)の
        // 結果だけを終了コードで受け取る(0=有効、非0=無効/判定不能)。
        // ダウンロード・展開・進捗表示は一切発生しないため、起動のたびに呼んでも
        // 体感できる遅延にはならない(ファイルI/O数回+JSON1回のパース程度)。
        // 例外・タイムアウト時はfalse(=フル実行へフォールバック、安全側)を返す。
        bool RunEnsureBlenderCheckOnly(string ensurePs1)
        {
            try
            {
                string args = string.Format(
                    "-NoProfile -ExecutionPolicy Bypass -File \"{0}\" -AppRoot \"{1}\" -CheckOnly",
                    ensurePs1, appRoot);
                var psi = new ProcessStartInfo(FindPwsh(), args)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                using (var p = Process.Start(psi))
                {
                    // マーカー検証だけなので即時終了するはずだが、万一詰まっても
                    // 起動フローをブロックし続けないよう上限を設ける(タイムアウト
                    // した場合はkillしてfalse=フル実行フォールバックへ)。
                    if (!p.WaitForExit(10000))
                    {
                        try { p.Kill(); } catch (Exception) { }
                        return false;
                    }
                    return p.ExitCode == 0;
                }
            }
            catch (Exception) { return false; }
        }

        // U54 WP-B(2026-07-27): バニラ準備(extract_vanilla.py)とライブテンプレート
        // (live_template.py)は完全にアバター非依存なので、Blenderが使える状態に
        // なった時点(ensure_blender完了後、Shownの最後)でバックグラウンドへ静かに
        // warm(事前計算)を投げておく。変換開始を1秒たりとも待たせない:
        //   - runningProc(変換本体)とは別プロセス扱いで起動し、UIも他の操作も
        //     一切ブロックしない(Process.Startして即戻るだけ、WaitForExitしない)
        //   - Palworldのpakが解決できない/Blender未セットアップ等で始められない
        //     場合は静かに諦める(ログのみ。変換時のオンデマンド構築に自然と
        //     フォールバックするので実害はない)
        //   - 変換(RunPipeline)と同時に走っても、共有キャッシュ側
        //     (vp_core.acquire_cache_lock)のロックで安全(warmが先に構築するか、
        //     変換側が先に構築してwarmは「既に新鮮」を検出して即終了するかのどちらか)
        void WarmSharedCacheOnStartup()
        {
            try
            {
                // dev#288 WP(prewarm): 以前はここの早期returnが完全に無音だった
                // ("実装した"と"効いている"は別、を自己検証するため各分岐にログを
                // 追加。UIには一切出さない(要件は不変)が、warm_startup.logを見れば
                // 「どのガードで止まったか」が後から追跡できるようにする。
                if (!blenderReady) { WarmDiagLog("warm-cache: skip (blenderReady=false)"); return; }
                string blender = FindBlender();
                if (!File.Exists(blender)) { WarmDiagLog("warm-cache: skip (blender.exe not found: " + blender + ")"); return; }
                string bpython = FindBlenderPython(blender);
                if (bpython == null || !File.Exists(bpython)) { WarmDiagLog("warm-cache: skip (bundled python not found under " + blender + ")"); return; }
                string pak = WarmCachePakPath();
                if (pak == null || !File.Exists(pak)) { WarmDiagLog("warm-cache: skip (pak not resolved: " + (pak ?? "null") + ")"); return; }
                string script = Path.Combine(appRoot, "pipeline", "py", "convert_noue.py");
                if (!File.Exists(script)) { WarmDiagLog("warm-cache: skip (convert_noue.py not found: " + script + ")"); return; }

                Directory.CreateDirectory(workRoot);
                string args = string.Format(
                    "\"{0}\" --warm-cache --pak \"{1}\" --work-root \"{2}\"",
                    script, pak, workRoot);
                var psi = new ProcessStartInfo(bpython, args)
                {
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8
                };
                string logPath = Path.Combine(workRoot, "warm_cache.log");
                DataReceivedEventHandler onData = delegate(object s, DataReceivedEventArgs e)
                {
                    if (e.Data == null) return;
                    try { File.AppendAllText(logPath, e.Data + Environment.NewLine, Encoding.UTF8); }
                    catch (Exception) { }
                };
                var proc = new Process { StartInfo = psi };
                proc.OutputDataReceived += onData;
                proc.ErrorDataReceived += onData;
                proc.EnableRaisingEvents = true;
                DateTime warmT0 = DateTime.UtcNow;
                proc.Exited += delegate
                {
                    try
                    {
                        double sec = (DateTime.UtcNow - warmT0).TotalSeconds;
                        WarmDiagLog(string.Format("warm-cache: exited code={0} elapsed={1:0.00}s", proc.ExitCode, sec));
                    }
                    catch (Exception) { }
                };
                proc.Start();
                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();
                WarmDiagLog("warm-cache: started pak=" + pak);
                // 意図的にWaitForExitはしない(撃ちっぱなし)。Exitedフックは
                // warm_startup.logへの完了記録専用で、UI・他処理は一切ブロックしない。
                // 失敗してもUIには一切出さない(ログファイルのみ、4.5の「失敗は無視」規定)。
            }
            catch (Exception ex)
            {
                // 失敗は無視。オンデマンド構築へ自然にフォールバックする(挙動は不変)。
                // ただし診断のため理由だけはログへ残す(try/catchで二重に握りつぶさない)。
                try { WarmDiagLog("warm-cache: exception " + ex.Message); } catch (Exception) { }
            }
        }

        // dev#288 WP(prewarm)共通: 起動時warm処理(キャッシュ構築・Blenderプリウォーム)の
        // 「何が起きた/起きなかったか」を1本のログへ集約する。UIには一切出さない
        // (4.5の「失敗は無視」規定を維持したまま、事後診断だけを可能にする)。
        void WarmDiagLog(string line)
        {
            try
            {
                Directory.CreateDirectory(workRoot);
                string path = Path.Combine(workRoot, "warm_startup.log");
                File.AppendAllText(path,
                    DateTime.UtcNow.ToString("o") + " " + line + Environment.NewLine,
                    Encoding.UTF8);
            }
            catch (Exception) { /* ログ自体の失敗で本処理を止めない */ }
        }

        // dev#288(2026-07-30、指揮者ミッション「変換の最適・最高速度化」由来):
        // 実測(work\speed_mission\measure\NOTES.md)で、step01(VRMインポート)の
        // 所要が同一セッション内で3〜18秒とブレることが判明し、原因はOSディスク
        // キャッシュ未ウォーム(初回Blender起動時のディスクI/O待ち)と推定された。
        // WarmSharedCacheOnStartup()はbpy(実Blenderプロセス)を一切使わない
        // pure-Pythonキャッシュ構築(extract_vanilla.py/live_template.pyはbpy
        // import無し)なので、Blender本体のexe/DLL群はそちらでは一切OSキャッシュに
        // 乗らない。ここでは無害な最小起動(--python-expr "pass"、即終了)を1回だけ
        // バックグラウンドで撃ちっぱなしにし、以後の実step01起動でOSファイル
        // キャッシュが効くことを狙う:
        //   - blenderReady確定後にのみ実行(呼び出し元のDoEnsureBlenderReady側で
        //     ok==trueの分岐からのみ呼ぶ)
        //   - runningProc(変換本体)が既に走っていれば実行しない(変換中は資源を
        //     譲る。呼び出し元でもpendingBlenderReadyAction!=null(=直後に変換が
        //     始まる)なら呼ばないようにしてあるが、念のためここでも二重に守る)
        //   - 失敗は静かにログのみ(warm_startup.log)。UIには一切出さない
        void WarmBlenderProcessOnStartup()
        {
            try
            {
                if (!blenderReady) { WarmDiagLog("blender-prewarm: skip (blenderReady=false)"); return; }
                if (runningProc != null) { WarmDiagLog("blender-prewarm: skip (conversion already running)"); return; }
                string blender = FindBlender();
                if (!File.Exists(blender)) { WarmDiagLog("blender-prewarm: skip (blender.exe not found: " + blender + ")"); return; }

                Directory.CreateDirectory(workRoot);
                string args = "--background --factory-startup --python-exit-code 0 --python-expr \"pass\"";
                var psi = new ProcessStartInfo(blender, args)
                {
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8
                };
                string logPath = Path.Combine(workRoot, "warm_blender.log");
                DataReceivedEventHandler onData = delegate(object s, DataReceivedEventArgs e)
                {
                    if (e.Data == null) return;
                    try { File.AppendAllText(logPath, e.Data + Environment.NewLine, Encoding.UTF8); }
                    catch (Exception) { }
                };
                var proc = new Process { StartInfo = psi };
                proc.OutputDataReceived += onData;
                proc.ErrorDataReceived += onData;
                proc.EnableRaisingEvents = true;
                DateTime t0 = DateTime.UtcNow;
                proc.Exited += delegate
                {
                    try
                    {
                        double sec = (DateTime.UtcNow - t0).TotalSeconds;
                        WarmDiagLog(string.Format("blender-prewarm: exited code={0} elapsed={1:0.00}s", proc.ExitCode, sec));
                    }
                    catch (Exception) { }
                };
                proc.Start();
                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();
                WarmDiagLog("blender-prewarm: started " + blender);
                // 撃ちっぱなし。WaitForExitしない(UIも他の処理も一切ブロックしない)。
            }
            catch (Exception ex)
            {
                try { WarmDiagLog("blender-prewarm: exception " + ex.Message); } catch (Exception) { }
            }
        }

        // convert.ps1の$BPython解決(Get-ChildItem (Split-Path $Blender)\*\python\bin\python.exe)
        // と同じ規則をC#側でも再現する(warm-cacheの起動にBlenderの同梱pythonを使うため)。
        string FindBlenderPython(string blenderExe)
        {
            try
            {
                string blenderDir = Path.GetDirectoryName(blenderExe);
                if (blenderDir == null) return null;
                foreach (string sub in Directory.GetDirectories(blenderDir))
                {
                    string candidate = Path.Combine(sub, "python", "bin", "python.exe");
                    if (File.Exists(candidate)) return candidate;
                }
            }
            catch (Exception) { }
            return null;
        }

        // WriteJob()のpaths.palworld_pak解決(WP16配線)と同じPaksDirQuiet()を使う。
        // ダイアログを一切出さない(warmは「静かに」が要件、GUI起動のたびに
        // フォルダ選択ダイアログを出すのは論外)。
        string WarmCachePakPath()
        {
            string paksDir = PaksDirQuiet();
            if (paksDir == null) return null;
            return Path.Combine(paksDir, PalWindowsPakName);
        }

        // ---------------- プレビューの鮮度(設定変更の追跡) ----------------

        string BuildPreviewSig()
        {
            // プレビューの見た目に影響する設定だけ(影の濃さ・影なしはBlenderプレビューに出ない)
            return string.Join("|", new string[] {
                vrmBox.Text.Trim(), shoulderBar.Value.ToString(),
                mergeFingersCheck.Checked.ToString(), dropBonesBox.Text.Trim() });
        }

        string SigFile()
        {
            string name = SanitizeName(Path.GetFileNameWithoutExtension(vrmBox.Text.Trim()));
            return Path.Combine(workRoot, name, "preview_sig.txt");
        }

        bool IsPreviewFresh()
        {
            try
            {
                string f = SigFile();
                if (!File.Exists(f)) return false;
                return File.ReadAllText(f, Encoding.UTF8) == BuildPreviewSig();
            }
            catch (Exception) { return false; }
        }

        void SavePreviewSig()
        {
            try { File.WriteAllText(SigFile(), BuildPreviewSig(), new UTF8Encoding(false)); }
            catch (Exception) { }
        }

        // ---------------- ボタンの有効/無効(押せない操作は押せなくする) ----------------

        // U51: noue(既定)で「影のみ更新」が使えるか = 前回のフル変換の中間成果が揃っているか。
        // 判定材料は pipeline\py\fast_repack.py が実際に再利用するディレクトリと同じ
        // (ここを増減するときは fast_repack.py 側の必須リストと必ず突き合わせること)。
        // 加えて build_provenance.json(convert_noue.py がフル変換の最後に書く)を要求し、
        // 「途中で中断した変換の残骸」で押せてしまうのを防ぐ。
        //
        // dev#42 item7(2026-07-29): U54 WP-Bで live_template の出力先が
        // このアバター固有の build\live_template から、アバター非依存の共有キャッシュ
        // work\_shared_cache\live_template\<fp12>\ へ移った(pipeline\py\live_template.py
        // build_live_template() 参照)。live_template はもう「このアバターがフル変換
        // 済みか」の証拠にならない(共有キャッシュなので他アバターの変換だけでも実在しうるし、
        // 逆にフル変換済みでもこのアバター固有のフォルダには存在しない)。したがって
        // このアバター固有のbuildディレクトリに残る3つ(noue_work\variant / atlas /
        // noue_mat_override)+ build_provenance.json だけで判定する。
        // これは fast_repack.py の実要求(必須ディレクトリ3つ+build_provenance.jsonの
        // 基準利用。live_templateはlive_template.build_live_template()に解決を委ねており
        // 存在チェックの対象にしていない)と厳密に一致させてある。
        bool HasNoueFullBuild()
        {
            string vrm = vrmBox.Text.Trim();
            if (vrm.Length == 0) return false;
            string name = SanitizeName(Path.GetFileNameWithoutExtension(vrm));
            string build = Path.Combine(workRoot, name, "build");
            string[] needDirs = {
                Path.Combine(build, "noue_work", "variant"),
                Path.Combine(build, "atlas"),
                Path.Combine(build, "noue_mat_override")
            };
            foreach (string d in needDirs)
                if (!Directory.Exists(d)) return false;
            return File.Exists(Path.Combine(build, "build_provenance.json"));
        }

        void UpdateButtonStates()
        {
            bool running = runningProc != null;
            // dev#236: Blenderのバックグラウンド取得中もこのバー(元は変換専用)を
            // 流用して見える化する。値自体はRunEnsureBlenderSetupProcess側の
            // ##PROGRESS##パース経由で直接更新される(このメソッドはVisibleだけ管理)。
            busyBar.Visible = running || blenderSetupRunning;
            // アバターの読み込み中は、保存済みの設定(削除ボーン・影の濃さ)がまだ画面に
            // 載っていない。この隙に変換を始めると古い設定でjob.jsonを書いてしまうので
            // 押させない(実際にはファイル数個の読み込みなので一瞬)
            bool busy = running || avatarLoading;
            bool hasVrm = File.Exists(vrmBox.Text.Trim());
            bool fresh = hasVrm && IsPreviewFresh();

            // u54: Blenderが未セットアップ(初回取得の失敗/キャンセル含む)の間は
            // 変換系ボタンをすべて押させない(convert.ps1に投げても必ず失敗するため)。
            // dev#298: workRootFailed(主系・フォールバック先とも書き込み不可)も同様に
            // 全押させない——job.json自体が書けないので、押しても必ず失敗するだけ
            convertButton.Enabled = !busy && hasVrm && fresh && blenderReady && !workRootFailed;
            previewButton.Enabled = !busy && hasVrm && blenderReady && !workRootFailed;
            // U51: 「影のみ更新」は前回のフル変換の中間成果が揃っている(build\live_template 等)
            // ことが前提。「一度もフル変換していないアバターでは押せない」ことが要件
            // (dev#114でUEモード判定を撤去、noue専用の判定のみ残す)。
            matsButton.Enabled = !busy && hasVrm && blenderReady && !workRootFailed && HasNoueFullBuild();
            if (matsHintLabel != null)
                matsHintLabel.Text = matsButton.Enabled ? "" : T("HintNeedFullConvertFirst");
            // 「変換を中止」はrunningProcを殺すボタン。バックグラウンドの読み込みとは無関係
            cancelButton.Enabled = running;
            applyButton.Enabled = pakList.SelectedItems.Count > 0;
            deleteButton.Enabled = !busy && pakList.SelectedItems.Count > 0;
            // dev#236: バックグラウンドで既に確認/取得が進行中なら再試行ボタンは隠す
            // (二重起動防止。EnsureBlenderReadyOnStartup側もblenderSetupRunningで
            // 二重起動を防いでいるので実害は無いが、押せても無駄なので見せない)
            blenderRetryButton.Visible = !blenderReady && !running && !blenderSetupRunning;

            // 無効ボタンはツールチップが出ないので、理由をステータス行で案内する
            if (!running)
            {
                // バックグラウンドで起きた失敗は握りつぶさず、ここで見せ続ける
                // (次にアバターを入れ直す/変換を始めるまで残る)。
                // dev#298: workRootFailedは最も根本的なブロッカー(job.json自体が書けない)
                // なので、他のどの理由よりも優先して案内する
                if (workRootFailed)
                    statusLabel.Text = T("TitleWorkRootUnwritable");
                else if (!blenderReady)
                    statusLabel.Text = blenderSetupMessage ?? T("StatusBlenderSetupNeeded");
                else if (backgroundError != null)
                    statusLabel.Text = backgroundError;
                else if (avatarLoading)
                    statusLabel.Text = T("StatusAvatarLoading");
                else if (!hasVrm)
                    statusLabel.Text = T("StatusPromptVrmDnd");
                else if (!fresh)
                    statusLabel.Text = T("StatusPreviewStale");
                else
                    statusLabel.Text = T("StatusReadyToConvert");
            }
        }

        void UpdateKodawariAvailability()
        {
        }

        // ---------------- 変換の実行 ----------------

        bool EnsureLicenseConfirmed()
        {
            if (licenseConfirmed) return true;
            var r = MessageBox.Show(
                T("MsgLicenseConfirmBody"),
                T("TitleLicenseConfirm"), MessageBoxButtons.YesNo, MessageBoxIcon.Question);
            if (r == DialogResult.Yes)
            {
                licenseConfirmed = true;
                return true;
            }
            return false;
        }

        void RunPipeline(bool previewOnly, bool materialsOnly, bool auto)
        {
            if (runningProc != null) { if (!auto) MessageBox.Show(T("MsgAlreadyRunning")); return; }
            if (!File.Exists(vrmBox.Text.Trim())) { if (!auto) MessageBox.Show(T("MsgSpecifyVrmFile")); return; }
            // MODを作る操作はアバター規約の確認(アバターごとに1回)が必要。プレビューは不要
            if (!previewOnly && !EnsureLicenseConfirmed()) return;
            // ここから先はこの実行のログ・ステータスが画面を占める。
            // 過去のバックグラウンド失敗の表示はここで役目を終える
            backgroundError = null;
            silentPreview = auto;
            string jobJson = WriteJob();
            string script = BuildConvertScriptPath();
            string args = BuildConvertArgs(script, jobJson, previewOnly, materialsOnly);

            string shell = FindPwsh();
            var psi = new ProcessStartInfo(shell, args)
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            MarkSessionStage(previewOnly ? "変換(プレビュー)" : materialsOnly ? "変換(影のみ更新)" : "変換(フル)");
            logBox.Clear();
            pipelineWarnings.Clear();
            LogPathHealthForThisRun();   // dev#134: この変換回のログにも環境要因を残す(再判定はしない)
            // dev#288 WP-UXIMPL 提案2: この実行のjobDirをAppendLog側から使えるように
            // 保存し、早期プレビュー再読込フラグをリセットする(前回実行の値を持ち越さない)。
            currentPipelineJobDir = Path.GetDirectoryName(jobJson);
            earlyPreviewLoadedThisRun = false;
            runningProc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            DataReceivedEventHandler onData = delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data == null) return;
                try { BeginInvoke((Action)delegate { AppendLog(e.Data); }); }
                catch (Exception) { }
            };
            runningProc.OutputDataReceived += onData;
            runningProc.ErrorDataReceived += onData;
            string jobDir = Path.GetDirectoryName(jobJson);
            runningProc.Exited += delegate
            {
                int code = runningProc.ExitCode;
                runningProc = null;
                try
                {
                    BeginInvoke((Action)delegate { OnPipelineDone(code, jobDir, previewOnly); });
                }
                catch (Exception) { }
            };
            runningProc.Start();
            runningProc.BeginOutputReadLine();
            runningProc.BeginErrorReadLine();
            busyBar.Style = ProgressBarStyle.Continuous;
            busyBar.Value = 0;
            UpdateButtonStates();
            statusLabel.Text = previewOnly ? T("StatusPreviewGenerating")
                : materialsOnly ? T("StatusMaterialsApplying") : T("StatusFullConverting");
        }

        // ---------------- Unityプロジェクトからの輸出(Modular Avatar等の前処理) ----------------
        // export_from_unity.ps1をバックグラウンド実行し、完了したFBXをそのまま
        // いつものアバター取り込み(SetVrm)へ渡す。UIはフリーズしない(RunPipelineと同じ非同期パターン)
        void RunUnityExport(string prefabPath)
        {
            if (runningProc != null)
            {
                MessageBox.Show(T("MsgOtherProcessRunning"));
                return;
            }
            if (!File.Exists(prefabPath) || !prefabPath.ToLower().EndsWith(".prefab"))
            {
                MessageBox.Show(T("MsgSpecifyPrefabFile"));
                return;
            }
            string script = Path.Combine(appRoot, "pipeline", "cli", "export_from_unity.ps1");
            if (!File.Exists(script))
            {
                MessageBox.Show(TF("MsgExportScriptNotFoundFormat", script));
                return;
            }
            string outDir = Path.Combine(workRoot,
                Path.GetFileNameWithoutExtension(prefabPath) + "_export");
            // dev#298: 以前はここで-Outを渡していなかったため、export_from_unity.ps1が
            // 独自に$PSScriptRoot基準の既定値($Root\work\<name>_export、$Root=Split-Path
            // (Split-Path $PSScriptRoot -Parent) -Parent=常にappRoot相当)を使っており、
            // C#側のoutDir(workRoot基準。workRootがフォールバックへ切り替わった場合は
            // appRoot\workと一致しなくなる)と食い違う余地があった。job.json/WriteJob()の
            // ようにworkRootを単一の真実の源にするため、outDirをそのまま明示的に渡す
            // (workRootが従来どおりappRoot\workのままの環境では見た目の挙動は変わらない)。
            string args = string.Format(
                "-NoProfile -ExecutionPolicy Bypass -File \"{0}\" -Prefab \"{1}\" -Out \"{2}\"",
                script, prefabPath, outDir);
            string shell = FindPwsh();
            var psi = new ProcessStartInfo(shell, args)
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            // 2026-07-26 LX: .prefabを選ぶのは常に「新しいアバターに取り掛かる」操作
            // (この後SetVrmが続くが、そちらはnewSession:falseでこのセッションを引き継ぐ)。
            // ここでセッションログをリセットしてから、この工程の区切りを刻む。
            sessionLog.Clear();
            MarkSessionStage("Unityエクスポート: " + Path.GetFileName(prefabPath));
            logBox.Clear();
            runningProc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            DataReceivedEventHandler onData = delegate(object s, DataReceivedEventArgs e)
            {
                if (e.Data == null) return;
                try { BeginInvoke((Action)delegate { AppendLog(e.Data); }); }
                catch (Exception) { }
            };
            runningProc.OutputDataReceived += onData;
            runningProc.ErrorDataReceived += onData;
            runningProc.Exited += delegate
            {
                int code = runningProc.ExitCode;
                runningProc = null;
                try { BeginInvoke((Action)delegate { OnUnityExportDone(code, outDir); }); }
                catch (Exception) { }
            };
            runningProc.Start();
            runningProc.BeginOutputReadLine();
            runningProc.BeginErrorReadLine();
            // 実進捗マーカーが無い工程(Unity起動〜インポート〜ベイク〜輸出)なのでマーキー表示にする
            busyBar.Style = ProgressBarStyle.Marquee;
            busyBar.MarqueeAnimationSpeed = 30;
            UpdateButtonStates();
            statusLabel.Text = T("StatusUnityExporting");
        }

        void OnUnityExportDone(int code, string outDir)
        {
            busyBar.Style = ProgressBarStyle.Continuous;
            UpdateButtonStates();
            // 2026-07-26 LX: Unity側が書く unity_export.log(数百KB、画面には出ない)は
            // サニタイズ除去記録・バインド行列不一致等、成功しても結果がおかしい系の
            // 不具合(例: 帽子が原点に落ちる)の手がかりを持っていることがある。
            // 丸ごとは大きすぎて貼れないので、要点だけをセッションログへ橋渡しする
            // (成否に関わらず。失敗時にも診断の手がかりになりうるため)。
            sessionLog.Append("\r\n").Append(
                ExtractUnityExportLogHighlights(Path.Combine(outDir, "unity_export.log")));
            if (code != 0)
            {
                statusLabel.Text = T("StatusUnityExportFailed");
                MessageBox.Show(T("MsgUnityExportErrorBody"), T("TitleUnityExportError"));
                return;
            }
            // 輸出フォルダから統合FBXを探して、そのままいつものアバター取り込みへ渡す
            string fbx = null;
            if (Directory.Exists(outDir))
            {
                var fbxFiles = Directory.GetFiles(outDir, "*.fbx");
                if (fbxFiles.Length > 0) fbx = fbxFiles[0];
            }
            if (fbx == null)
            {
                statusLabel.Text = T("StatusUnityExportNoFbx");
                MessageBox.Show(TF("MsgUnityExportNoFbxFormat", outDir), T("TitleUnityExport"));
                return;
            }
            statusLabel.Text = T("StatusUnityExportDone");
            // newSession:false — Unity輸出の続きなので、直前に積んだセッションログ
            // (輸出の記録+unity_export.logの要点)を消さずに、この後の変換工程も
            // 同じセッションログへ積み増していく
            SetVrm(fbx, false);
        }

        string FindPwsh()
        {
            // PATHからpwshを探す(Store版はProgram Files\PowerShell\7に居ない)。
            // 見つからなければWindows PowerShell 5.1(convert.ps1は5.1互換で書く)
            string pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (string dir in pathEnv.Split(';'))
            {
                try
                {
                    string cand = Path.Combine(dir.Trim(), "pwsh.exe");
                    if (File.Exists(cand)) return cand;
                }
                catch (Exception) { }
            }
            string pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string pwsh = Path.Combine(pf, "PowerShell", "7", "pwsh.exe");
            if (File.Exists(pwsh)) return pwsh;
            return "powershell.exe";
        }

        // 2026-07-26 LX追加: unity_export.log(Unity自体が -logFile で書く生ログ。
        // 実測20〜30万文字級)から、診断に効く行だけを抜き出す。
        // 全部拾うと大きすぎて貼れなくなるので、次の2種類だけに絞る:
        //   - "D2P:" で始まる行 … このツール自身がUnity側で仕込んでいる意図的な
        //     診断出力(サニタイズ除去記録、バインド行列不一致の警告、
        //     ブレンドシェイプ焼き込み件数等)。全て unity\DiveToPalworldExporter.cs の
        //     Debug.Log/Debug.LogWarning由来で、ノイズではなく狙って出している行。
        //   - 例外の安全網("Exception:" "error CS" "UnityException") …
        //     手元のサンプルでは未発生だが、今後Unity側が本当にクラッシュした場合の保険。
        // 除外(意図的): Unityのライセンス確認が出す"[Licensing::Client] Error"や
        // シャットダウン時の"abort_threads: Failed aborting"は、work\配下の
        // 実ログ30件全てで例外なく出現するヘッドレス起動の定型ノイズと確認済みで
        // (grep実測)、"D2P:"接頭辞を持たないため自然に除外される。
        // 参考: pipeline\cli\convert.ps1 の Write-UnityExportSanitizeHint が
        // 同じ発想(サニタイズ行だけをgrepして橋渡し)を先にやっていた。
        // ここではその対象をD2P:診断行全般+例外の安全網へ広げた。
        static readonly Regex UnityLogHighlightPattern =
            new Regex("D2P:|Exception:|error CS\\d|UnityException");

        // 2026-07-26 LX追加(大崎商会PC実機で発覚した不具合の修正): Unityプロセスが
        // 終了した直後でも、OSやウイルス対策ソフトがログファイルのハンドルを
        // 一瞬掴んだままのことがあり、File.ReadAllLines(既定の共有モード=FileShare.Read、
        // つまり他プロセスの書き込みロックを許容しない)がIOExceptionで失敗していた
        // (実機エラー: "別のプロセスで使用されているため、プロセスはファイル
        // '...\unity_export.log' にアクセスできません。")。
        // FileShare.ReadWriteで開き直し(他プロセスの読み書きロックを許容する)、
        // それでも一瞬の競合で失敗する場合に備えて短い間隔で数回だけリトライする。
        // ここはUIスレッド(BeginInvoke経由)から呼ばれるが、合計待ち時間は最大でも
        // 900ms程度(Unity輸出自体は数十秒〜かかる工程の直後の一度きりの遅延なので、
        // 体感への影響は無視できる)
        static string[] ReadAllLinesShared(string path)
        {
            int[] retryDelaysMs = { 0, 300, 600 };
            Exception last = null;
            foreach (int delay in retryDelaysMs)
            {
                if (delay > 0) System.Threading.Thread.Sleep(delay);
                try
                {
                    using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                    using (var sr = new StreamReader(fs, Encoding.UTF8))
                    {
                        var list = new List<string>();
                        string line;
                        while ((line = sr.ReadLine()) != null) list.Add(line);
                        return list.ToArray();
                    }
                }
                catch (IOException ex) { last = ex; }
            }
            throw last;
        }

        string ExtractUnityExportLogHighlights(string logPath)
        {
            var sb = new StringBuilder();
            if (!File.Exists(logPath))
            {
                sb.Append("--- Unityエクスポートログ(unity_export.log)は見つかりませんでした: ")
                  .Append(logPath).Append(" ---\r\n");
                return sb.ToString();
            }
            string[] lines;
            try { lines = ReadAllLinesShared(logPath); }
            catch (Exception ex)
            {
                sb.Append("--- Unityエクスポートログの読み込みに失敗しました: ").Append(ex.Message).Append(" ---\r\n");
                return sb.ToString();
            }
            var hits = new List<string>();
            foreach (string l in lines)
            {
                if (UnityLogHighlightPattern.IsMatch(l)) hits.Add(l);
            }
            sb.Append("--- Unityエクスポートログの要点(全").Append(lines.Length).Append("行中")
              .Append(hits.Count).Append("行を抽出。全文はここ: ").Append(logPath).Append(") ---\r\n");
            if (hits.Count == 0)
            {
                sb.Append("(D2P:診断行・例外らしき行は見つかりませんでした)\r\n");
            }
            else
            {
                foreach (string h in hits) sb.Append(h).Append("\r\n");
            }
            sb.Append("--- 要点ここまで ---\r\n");
            return sb.ToString();
        }

        static readonly Regex AnsiEscape = new Regex("\x1b\\[[0-9;]*[A-Za-z]");
        static readonly Regex ProgressMark = new Regex("##PROGRESS## (\\d+) (.*)");
        // 2026-07-26追加: convert_noue.py が出す「ビルドは通ったが見た目が
        // 崩れる可能性がある」警告(UVタイル境界をまたぐ面の除外等)。
        // ログ欄にも通常どおり残しつつ、内容はpipelineWarningsへ集めて
        // OnPipelineDone完了時のダイアログでも明示提示する(ログ欄だけでは
        // スクロールに埋もれて見落とされるため)。
        static readonly Regex AvatarWarnMark = new Regex("##AVATAR_WARNING## (.*)");

        void AppendLog(string line)
        {
            // 保険: Blender/UE等が吐くANSIカラーコードを剥がしてから表示する
            string clean = AnsiEscape.Replace(line, "");
            // 進捗マーカーはバーとステータスに反映(ログ欄には出さない)
            var pm = ProgressMark.Match(clean);
            if (pm.Success)
            {
                int pct;
                if (int.TryParse(pm.Groups[1].Value, out pct) && runningProc != null)
                {
                    busyBar.Value = Math.Max(0, Math.Min(100, pct));
                    // dev#304裁定A: 進捗ラベルは多言語化の対象内。辞書(Strings.ProgressLabels/
                    // ProgressLabelTemplates)にあれば翻訳、無ければ原文表示(フォールバック)
                    statusLabel.Text = Strings.TranslateProgressLabel(pm.Groups[2].Value.Trim())
                        + "... (" + pct + "%)";
                    // dev#288 WP-UXIMPL 提案2: Phase1完了(39%到達)時点でプレビュー画像は
                    // 既に生成済み(gender並列ブロックのrender_preview.py実行が担当)。
                    // OnPipelineDone(全工程完了後)を待たずここで1回だけ再読込することで、
                    // 「設定変更後に直接フル変換」した場合の新プレビュー反映が30〜59秒早まる。
                    // 失敗してもフル変換本体には一切影響させない(try/catchで握り、
                    // 画面には出さずセッションログにだけ残す=「静かにログのみ」)。
                    if (pct >= 39 && !earlyPreviewLoadedThisRun
                        && !string.IsNullOrEmpty(currentPipelineJobDir))
                    {
                        earlyPreviewLoadedThisRun = true;
                        try { LoadPreviews(currentPipelineJobDir); }
                        catch (Exception ex)
                        {
                            sessionLog.Append("[preview-early] LoadPreviews failed at pct=")
                                .Append(pct).Append(": ").Append(ex.Message).Append("\r\n");
                        }
                    }
                }
                return;
            }
            var wm = AvatarWarnMark.Match(clean);
            if (wm.Success)
            {
                pipelineWarnings.Add(wm.Groups[1].Value.Trim());
            }
            logBox.AppendText(clean + "\r\n");
            // 2026-07-26 LX: 画面表示(logBox)と同じ内容をセッション全体ログにも残す。
            // logBoxは工程が変わるとClear()されるが、sessionLogはされない。
            sessionLog.Append(clean).Append("\r\n");
        }

        // 2026-07-26 LX追加: 新しい工程(Unity輸出/変換)を始める時にセッションログへ
        // 区切りを刻む。logBoxはこの直後にClear()されて画面には最新工程だけが出るが、
        // sessionLogは消えないので、コピー時にどの工程がどこで始まったか分かる。
        void MarkSessionStage(string stageLabel)
        {
            sessionLog.Append("\r\n=== ").Append(stageLabel).Append(" (")
                .Append(DateTime.Now.ToString("HH:mm:ss")).Append(") ===\r\n");
        }

        void OnPipelineDone(int code, string jobDir, bool previewOnly)
        {
            UpdateButtonStates();
            if (code != 0)
            {
                statusLabel.Text = T("StatusFailedOrCancelled");
                return;
            }
            LoadPreviews(jobDir);
            // 2026-07-26追加: ##AVATAR_WARNING## を拾っていたら、ログ欄だけに
            // 頼らずここで必ず1回ダイアログ提示する(見た目崩れの可能性がある、
            // という重要な注意なので完了メッセージに埋もれさせない)
            if (pipelineWarnings.Count > 0)
            {
                MessageBox.Show(
                    TF("MsgConvertDoneWithWarningsFormat", string.Join("\n\n", pipelineWarnings.ToArray())),
                    T("TitleConvertDoneWithWarnings"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            if (previewOnly)
            {
                SavePreviewSig();
                UpdateButtonStates();  // フル変換ボタンがここで解禁される
                statusLabel.Text = T("StatusPreviewDone");
                if (!silentPreview)
                    MessageBox.Show(T("MsgPreviewDoneBody"), T("TitlePreviewDone"));
            }
            else
            {
                statusLabel.Text = T("StatusConvertDone");
                RefreshPakList();
                // 完成したMODを一覧で自動選択(そのまま「Palworldに適用」を押せる状態に)
                string avatar = Path.GetFileName(jobDir);
                bool foundItem = false;
                foreach (ListViewItem item in pakList.Items)
                {
                    if (item.SubItems[0].Text == avatar)
                    {
                        item.Selected = true;
                        item.EnsureVisible();
                        foundItem = true;
                        break;
                    }
                }
                UpdateButtonStates();
                // 「自動で適用」がONなら、既存の「Palworldに適用」ボタンと全く同じ処理
                // (ApplySelected)をそのまま呼ぶ。ゲーム起動中の警告やコピー失敗時のダイアログも
                // ApplySelected側がそのまま出す(ここでは呼ぶかどうかの判断しかしない)。
                // ここは previewOnly=false のこの分岐にしか来ないので、
                // 「フル変換」「影のみ更新」のどちらでも効き、失敗(code!=0)時は
                // メソッド冒頭のreturnで既にこの分岐へ到達しないので実行されない
                bool autoApplied = false;
                if (autoApplyCheck.Checked && foundItem)
                {
                    ApplySelected();
                    autoApplied = true;
                }
                if (!autoApplied)
                {
                    MessageBox.Show(T("MsgConvertDoneBody"), T("TitleConvertDone"));
                }
            }
        }

        void LoadPreviews(string jobDir)
        {
            string front = Path.Combine(jobDir, "converted", "preview_male_stand.png");
            string side = Path.Combine(jobDir, "converted", "preview_male_stand_side.png");
            if (File.Exists(front)) previewFront.Image = LoadImageNoLock(front);
            if (File.Exists(side)) previewSide.Image = LoadImageNoLock(side);
        }

        Image LoadImageNoLock(string path)
        {
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read))
            {
                return Image.FromStream(fs);
            }
        }

        // ---------------- MOD一覧と適用/解除/削除 ----------------

        // WP16(公開issue #8): Palworldが既定のCドライブ以外にインストールされて
        // いる環境で、Mod適用(このPaksDir()系列)は元々ダイアログで救済できていたが、
        // バニラ抽出(pipeline\py側のpaths.palworld_pak)には配線されておらず、
        // 変換前の時点で失敗していた。ここでは「フォルダが見つかった」だけで
        // 満足せず、Pal-Windows.pak本体の実在まで確認する(フォルダはあるが
        // pakが無い=未解決 扱い。移動済み/アンインストール後の残骸フォルダに
        // 誤って乗る事故を防ぐ)。自動探索はpipeline\py\palworld_locate.pyと
        // 同じ方針(レジストリ→Steamのlibraryfolders.vdf→既定パス)。
        // 実装は言語が違うため別コードだが、探索順序・pak実在確認という
        // 考え方を1本に揃えてある(二重実装を増やさない)。
        const string PalWindowsPakName = "Pal-Windows.pak";

        static bool PaksDirHasPak(string dir)
        {
            return !string.IsNullOrEmpty(dir) && Directory.Exists(dir)
                && File.Exists(Path.Combine(dir, PalWindowsPakName));
        }

        static List<string> DistinctPreserveOrder(IEnumerable<string> items)
        {
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var outp = new List<string>();
            foreach (string it in items)
            {
                if (string.IsNullOrEmpty(it)) continue;
                string norm = it.TrimEnd('\\', '/');
                if (seen.Add(norm.ToLowerInvariant())) outp.Add(norm);
            }
            return outp;
        }

        // Steamのインストールルート候補(レジストリ優先、既定パスは最後の保険)
        static List<string> SteamRootCandidates()
        {
            var roots = new List<string>();
            try
            {
                using (var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Valve\Steam"))
                {
                    if (key != null)
                    {
                        object v = key.GetValue("SteamPath") ?? key.GetValue("InstallPath");
                        if (v != null) roots.Add(v.ToString());
                    }
                }
            }
            catch (Exception) { }
            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\WOW6432Node\Valve\Steam"))
                {
                    if (key != null)
                    {
                        object v = key.GetValue("InstallPath");
                        if (v != null) roots.Add(v.ToString());
                    }
                }
            }
            catch (Exception) { }
            roots.Add(@"C:\Program Files (x86)\Steam");
            roots.Add(@"C:\Program Files\Steam");
            return DistinctPreserveOrder(roots);
        }

        // steamRoot配下のlibraryfolders.vdfから登録済み全ライブラリの"path"を集める
        // (steamRoot自身も1ライブラリとして含める)。KeyValues完全パーサは持たず、
        // "path"の値を正規表現で拾うだけ(実在確認はファイルシステム側でやる設計)。
        static List<string> SteamLibraryRoots(string steamRoot)
        {
            var libs = new List<string>();
            if (string.IsNullOrEmpty(steamRoot)) return libs;
            libs.Add(steamRoot);
            string vdf = Path.Combine(steamRoot, @"steamapps\libraryfolders.vdf");
            if (File.Exists(vdf))
            {
                try
                {
                    string text = File.ReadAllText(vdf);
                    foreach (Match m in Regex.Matches(text, "\"path\"\\s*\"([^\"]*)\""))
                    {
                        string p = m.Groups[1].Value.Replace("\\\\", "\\");
                        if (p.Length > 0) libs.Add(p);
                    }
                }
                catch (Exception) { }
            }
            return DistinctPreserveOrder(libs);
        }

        // 自動探索(ダイアログなし)。見つからなければnull
        static string AutoDiscoverPaksDir()
        {
            foreach (string steamRoot in SteamRootCandidates())
            {
                foreach (string lib in SteamLibraryRoots(steamRoot))
                {
                    string paks = Path.Combine(lib, @"steamapps\common\Palworld\Pal\Content\Paks");
                    if (PaksDirHasPak(paks)) return paks;
                }
            }
            return null;
        }

        string PaksDir()
        {
            if (PaksDirHasPak(paksDirCache)) return paksDirCache;
            string saved = Path.Combine(appRoot, "settings_paksdir.txt");
            if (File.Exists(saved))
            {
                string p = File.ReadAllText(saved).Trim();
                if (PaksDirHasPak(p)) { paksDirCache = p; return p; }
            }
            string auto = AutoDiscoverPaksDir();
            if (auto != null)
            {
                File.WriteAllText(saved, auto);
                paksDirCache = auto;
                return auto;
            }
            // 自動探索でも見つからない場合のみダイアログ(WP16: pakが無いフォルダを
            // 選んだ場合は理由を伝えて再度ダイアログを出す。無言で受理しない)
            while (true)
            {
                using (var dlg = new FolderBrowserDialog
                {
                    Description = T("DlgDescPaksFolder")
                })
                {
                    if (dlg.ShowDialog() != DialogResult.OK) return null;
                    if (PaksDirHasPak(dlg.SelectedPath))
                    {
                        File.WriteAllText(saved, dlg.SelectedPath);
                        paksDirCache = dlg.SelectedPath;
                        return paksDirCache;
                    }
                    MessageBox.Show(this,
                        TF("MsgPaksNotFoundFormat", PalWindowsPakName, dlg.SelectedPath),
                        T("TitlePalworldNotFound"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
            }
        }

        bool IsGameRunning()
        {
            return Process.GetProcessesByName("Palworld-Win64-Shipping").Length > 0;
        }

        // ---------------- 対応パルワールドバージョンの確認 ----------------
        // パルワールド本体が更新されると、バニラ資産の構造が変わって変換が壊れうる。
        // 検証済みのバージョンを覚えておき、違っていたら**警告する**(ブロックはしない。
        // 動くかもしれないのでユーザーが続行を選べること)。
        //
        // 何を見てバージョンを判定するか(2026-07-25 実測で選定):
        //   ① Steam の appmanifest_1623730.acf の buildid — 単調増加でビルドを一意に特定できる。
        //      本命。<Paks>\..\..\..\..\appmanifest_1623730.acf に位置する
        //   ② Pal-Windows.pak のサイズ — Steam以外/移動済みインストールでも効く保険。
        //      パイプライン側も live_template のキャッシュ判定にこの値を使っている
        // 採らなかったもの: Palworld-Win64-Shipping.exe のバージョン情報は
        //   FileVersion が空で、取れるのは UE エンジンの 5.1.1.0 だけ。ゲーム版数と無関係で使えない。
        // work\<avatar>\vanilla\version.txt は**我々の抽出器のスキーマ版数**(extract_vanilla.py の
        //   VANILLA_VERSION)であって、パルワールドのバージョンではない。流用不可。
        //
        // dev#87/#89/#91(wp878991、2026-07-29): 単一の「検証済みバージョン」定数を
        // ハードコードする旧方式は、パルワールドが更新されるたび**必ず**擬陽性警告を
        // 出す構造的欠陥だった(dev#87実測: v1.0.2でv1.0.1検証済みの警告が出るが、
        // 実際は変換が消費する材料は完全不変=無害)。新方式は2階層:
        //   1) 既知版番号リスト(known_versions、buildid+pakサイズの組)を1件constでなく
        //      pipeline\py\known_good_palworld.json(同梱データ、複数件持てる)+
        //      dl.osakishokai.com/versions.json の任意拡張(dev#89、取得失敗時は無視)
        //      から作る。判定ロジック本体は PalworldCompat(このファイル末尾の独立
        //      静的クラス、--check-palworld-compat で単体試験可能)に切り出した。
        //   2) 1)が未知でも、抽出物マニフェスト(vanilla_manifest.json の combined_hash、
        //      pipeline\py\extract_vanilla.py dev#91)が既知良好と一致すれば警告しない
        //      (版番号ではなく「変換が実際に消費する材料」で互換を自己判定する)。
        // 判定に使うデータの型・マージ・評価ロジックは PalworldCompat 参照。

        // dev#98/#103: 与えられたPaksフォルダ内の、自分自身(InstallName/レガシー名)と
        // バニラ本体(Pal-Windows.pak)を除いた他の.pak件数を返す。判定不能
        // (フォルダ不明/未存在)ならnullを返す。dev#103裁定「診断ログにファイル名を
        // そのまま列挙してよいか」への答えが伏字化(拡張子と件数のみ)だったため、
        // ファイル名は一切保持しない(rd_98 PROPOSAL.mdのOtherPakSummaryLine案は
        // 名前列挙前提だったため不採用)。純粋関数(instance状態・PaksDirQuiet()の
        // 自動探索に依存しない)にしてあるのは、--check-other-pak隠しCLI(下記)から
        // 実機のPalworld設置状況に左右されず単体試験できるようにするため
        // (既存の--check-i18n/--check-palworld-compatと同じ動機)
        static int? CountOtherPaks(string paksDir)
        {
            if (paksDir == null || !Directory.Exists(paksDir)) return null;
            var exclude = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                InstallName, PalWindowsPakName
            };
            foreach (var legacy in LegacyInstallNames) exclude.Add(legacy);
            try
            {
                int count = 0;
                foreach (string f in Directory.GetFiles(paksDir, "*.pak"))
                {
                    if (!exclude.Contains(Path.GetFileName(f))) count++;
                }
                return count;
            }
            catch (Exception) { return null; }
        }

        // 診断ログ用の1行。ファイル名は出さない(dev#103裁定どおり伏字化)。
        static string SummarizeOtherPaks(int? n)
        {
            if (n == null) return "other_paks: unknown (paks dir not found)";
            if (n.Value == 0) return "other_paks: none";
            return "other_paks: " + n.Value + " (.pak)";
        }

        int? OtherPakCount()
        {
            return CountOtherPaks(PaksDirQuiet());
        }

        string OtherPakSummaryLine()
        {
            return SummarizeOtherPaks(OtherPakCount());
        }

        // dev#103(裁定2026-07-29「他MOD共存は一切対応しない/検出した時点でNG」): 起動時に
        // 他の.pakを検出したら警告のみ表示する(変換のブロックまでは裁定されていないため
        // ブロックしない)。CheckPalworldVersionOnce()と同じくディスクI/Oを起動直後の
        // UIスレッドで固めないよう、専用バックグラウンドスレッドに乗せる
        void CheckOtherModsOnce()
        {
            var thread = new System.Threading.Thread(delegate ()
            {
                int? n;
                try { n = OtherPakCount(); }
                catch (Exception) { return; }
                if (n == null || n.Value == 0) return;
                int count = n.Value;
                PostToUi(delegate
                {
                    AppendLog("Warning: " + count + " other .pak file(s) detected in the Paks folder "
                        + "— running Uchinoko for Palworld alongside other mods is not supported");
                    MessageBox.Show(this,
                        TF("MsgOtherModsDetectedFormat", count.ToString(CultureInfo.InvariantCulture)),
                        T("TitleOtherModsDetected"),
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
                });
            });
            thread.IsBackground = true;
            thread.Name = "OtherModsCheck";
            thread.Start();
        }

        // ---------------- dev#134: インストール/作業先パスの自動健全性チェック ----------------
        // rd_125第14案(GUI内「自己診断」ボタン)は2026-07-29ぱん裁定でボタン案を却下、
        // 「自動で診断して、エラーで出すなり自己修正」する方針へ転換された(dev#134コメント
        // 参照)。他の診断要素(Blender検出=EnsureBlenderReadyOnStartup、Palworld版判定=
        // CheckPalworldVersionOnce/PalworldCompat、他MOD検出=CheckOtherModsOnce)は既に
        // 「起動時自動実行+AppendLogでセッションログに残る+必要なら警告」を満たしている
        // ため、ここで重複させて二重警告にはしない。新設するのはこれまで無かった
        // 「インストール/作業先パスの健全性」(非ASCII/UNC/OneDrive配下/パス長)だけ:
        // pipeline\cli\convert.ps1のGet-PathFacts(失敗直後の診断用に既存)と同じ観点を
        // 事前チェックへ転用したもの(BuildPathFacts/PathHealthProblem/PathHealthLine、
        // ファイル末尾寄りに配置。単体表は--check-path-health隠しCLI参照)。
        //
        // ぱん裁定の3分類:
        //   (a) 自己修正可能→黙って修正: パス自体は自動移動できないため該当なし
        //   (b) ユーザー操作が要る→次アクション付き警告: リスクありと判定した時、
        //       既存のCause/Actionペア方式(ShowApplyFailure/MsgApplyFailureBodyFormatと
        //       同じ型)でMessageBoxとAppendLogの両方に出す
        //   (c) 正常→ログに構造を残すのみ: 健全な時はAppendLogに1行だけ残す(無言の
        //       打ち切りにしない。CLAUDE.md「成功時にも構造が残らないと診断できない」)
        //
        // 起動時(Shown)に1回判定・警告し、さらに変換開始のたび(RunPipeline)にも同じ
        // 事実をログへ再掲する(LogPathHealthForThisRun)。appRoot/workRootの位置は
        // アプリ起動中に変わらないため再判定はしない(判定済みの結果を再掲するだけ)。
        // 再掲する理由は、問い合わせ時に「その変換回のログ」だけを見ても環境要因が
        // 追えるようにするため(CLAUDE.mdの「成功したのに結果が変」系の問い合わせ実例で、
        // 実行毎のログに環境要因が残っていることが決め手になった教訓を踏まえる)。
        // dev#298: workRoot決定(自動→フォールバック→ログの三点セット)の結果を1行に
        // まとめる。フォールバックが起きた/起きなかったに関わらず必ず出す
        // (「成功時にも構造が残らないと診断できない」CLAUDE.md方針)。
        string WorkRootResolutionLine()
        {
            if (!workRootUsedFallback && !workRootFailed)
                return "work_root: " + workRoot + " (install location, writable)";
            if (workRootUsedFallback)
                return "work_root: " + workRoot + " (fallback to a user-writable location; "
                    + "install location \"" + workRootPrimaryPath + "\" is not writable: "
                    + workRootPrimaryError + ")";
            return "work_root: " + workRoot + " [!] neither the install location (\""
                + workRootPrimaryPath + "\": " + workRootPrimaryError + ") nor the fallback (\""
                + workRootFallbackPath + "\": " + workRootFallbackError + ") is writable";
        }

        void CheckPathHealthOnStartup()
        {
            PathHealthFacts install, work;
            ComputePathHealthFacts(out install, out work);

            AppendLog(PathHealthLine(install));
            AppendLog(PathHealthLine(work));
            AppendLog(WorkRootResolutionLine());

            // dev#298: 主系・フォールバック先ともに書き込み不可(稀)は、他のパス健全性
            // 警告とは別枠の明確なエラーとして案内する(自動修復のしようがない、
            // ユーザー操作が必須のケースのため)。変換系ボタンはUpdateButtonStatesが
            // workRootFailedを見て無効化する。
            if (workRootFailed)
            {
                AppendLog("[!] " + T("TitleWorkRootUnwritable"));
                MessageBox.Show(this,
                    TF("MsgWorkRootUnwritableFormat", workRootPrimaryPath, workRootFallbackPath),
                    T("TitleWorkRootUnwritable"), MessageBoxButtons.OK, MessageBoxIcon.Error);
            }

            if (!PathHealthProblem(install) && !PathHealthProblem(work)) return;

            var bullets = new List<string>();
            if (PathHealthHasTooLong(install) || PathHealthHasTooLong(work))
                bullets.Add("- " + T("CausePathTooLong") + " / " + T("ActionPathTooLong"));
            if (install.Unc || work.Unc)
                bullets.Add("- " + T("CausePathUnc") + " / " + T("ActionPathUnc"));
            if (install.UnderOneDrive || work.UnderOneDrive)
                bullets.Add("- " + T("CausePathOneDrive") + " / " + T("ActionPathOneDrive"));

            string detail = PathHealthLine(install) + "\n" + PathHealthLine(work);
            AppendLog("[!] " + T("TitlePathHealthWarning") + ": " + string.Join(" / ", bullets.ToArray()));
            MessageBox.Show(this,
                TF("MsgPathHealthRiskFormat", string.Join("\n", bullets.ToArray()), detail),
                T("TitlePathHealthWarning"), MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        // 変換開始のたびに呼ぶ(RunPipeline冒頭)。事実は起動時から変わらないため
        // 再判定はせず、その変換回のログにも環境要因が残るように再掲するだけ
        // (ポップアップは起動時の1回のみ。ここでは出さない)。
        void LogPathHealthForThisRun()
        {
            PathHealthFacts install, work;
            ComputePathHealthFacts(out install, out work);
            AppendLog(PathHealthLine(install));
            AppendLog(PathHealthLine(work));
            AppendLog(WorkRootResolutionLine());
        }

        void ComputePathHealthFacts(out PathHealthFacts install, out PathHealthFacts work)
        {
            string oneDrive = null;
            try { oneDrive = Environment.GetEnvironmentVariable("OneDrive"); }
            catch (Exception) { }
            install = BuildPathFacts("install", appRoot, oneDrive);
            work = BuildPathFacts("work", workRoot, oneDrive);
        }

        // ダイアログを出さずに Paks フォルダを探す(起動時の確認でユーザーに問わないため)
        string PaksDirQuiet()
        {
            if (PaksDirHasPak(paksDirCache)) return paksDirCache;
            try
            {
                string saved = Path.Combine(appRoot, "settings_paksdir.txt");
                if (File.Exists(saved))
                {
                    string p = File.ReadAllText(saved).Trim();
                    if (PaksDirHasPak(p)) return p;
                }
            }
            catch (Exception) { }
            return AutoDiscoverPaksDir();
        }

        static string ReadSteamBuildId(string paks)
        {
            // <...>\steamapps\common\Palworld\Pal\Content\Paks → <...>\steamapps
            try
            {
                var d = new DirectoryInfo(paks);
                for (int i = 0; i < 5 && d != null; i++) d = d.Parent;   // Content, Pal, Palworld, common, steamapps
                if (d == null) return null;
                string acf = Path.Combine(d.FullName, "appmanifest_1623730.acf");
                if (!File.Exists(acf)) return null;
                foreach (string line in File.ReadAllLines(acf))
                {
                    // 	"buildid"		"24181527"
                    int k = line.IndexOf("\"buildid\"", StringComparison.OrdinalIgnoreCase);
                    if (k < 0) continue;
                    var parts = line.Substring(k + 9).Split(new[] { '"' }, StringSplitOptions.RemoveEmptyEntries);
                    foreach (string p in parts)
                    {
                        string s = p.Trim();
                        if (s.Length == 0) continue;
                        bool digits = true;
                        foreach (char c in s) if (!char.IsDigit(c)) { digits = false; break; }
                        if (digits) return s;
                    }
                }
            }
            catch (Exception) { }
            return null;
        }

        // dev#89: dl.osakishokai.com/versions.json の任意フィールド"palworld_known_good"
        // だけをCheckForUpdateOnStartup()が取得できたときにここへキャッシュする
        // (JsonObj()で既に切り出し済みの断片。全文は保持しない)。取得前/失敗時/
        // オフライン時はnullのまま(=同梱データのみで判定、安全に縮退)。
        volatile string remoteKnownGoodJson;

        string KnownGoodBundledPath()
        {
            return Path.Combine(appRoot, "pipeline", "py", "known_good_palworld.json");
        }

        // convert_noue.py _warm_job()が使うjob_dir固定名("_warm_dummy")と、
        // extract_vanilla._sync_job_local_copy()がそのままコピーする既定ファイル名
        // (vanilla_manifest.json)に合わせた固定パス。Python側のfingerprintハッシュ
        // (build_fingerprint()、pak mtime等machine依存値込み)をC#側で1バイトも
        // 違わず再現する必要をなくすための選択(既存機構の再利用、入口で正規化の原則。
        // 詳細はpipeline\py\extract_vanilla.pyのU54 WP-Bコメント参照)。
        string PalworldManifestBreadcrumbPath()
        {
            return Path.Combine(workRoot, "_warm_dummy", "vanilla", "vanilla_manifest.json");
        }

        KnownGoodPalworld LoadKnownGood()
        {
            string bundled = "";
            try { bundled = File.ReadAllText(KnownGoodBundledPath(), Encoding.UTF8); }
            catch (Exception) { }   // 同梱データが読めない(パッケージング事故)= 空リストのまま。
                                    // 空でも動作は変わらない(常に「既知一致なし」寄りに倒れるだけ)
            return PalworldCompat.MergeKnownGood(bundled, remoteKnownGoodJson);
        }

        PalworldDetection DetectPalworldVersion()
        {
            var det = new PalworldDetection();
            string paks = PaksDirQuiet();
            if (paks == null) return det;   // 場所が判らない = 判定不能。従来どおり黙って動く
            det.Detected = true;
            det.BuildId = ReadSteamBuildId(paks);
            try
            {
                string pak = Path.Combine(paks, "Pal-Windows.pak");
                if (File.Exists(pak)) det.PakSize = new FileInfo(pak).Length;
            }
            catch (Exception) { }
            return det;
        }

        string ReadManifestCombinedHash()
        {
            try
            {
                string path = PalworldManifestBreadcrumbPath();
                if (!File.Exists(path)) return null;
                return JsonStr(File.ReadAllText(path, Encoding.UTF8), "combined_hash");
            }
            catch (Exception) { return null; }
        }

        /// <summary>今この瞬間の状態から判定する(待たない、I/O一式込み)。
        /// BuildDiagnosticsText()のログ行と、CheckPalworldVersionOnce()の判定の
        /// どちらからも呼ぶ共通経路(1箇所にまとめることで両者の判定基準を必ず一致させる)。</summary>
        PalworldCompatStatus EvaluateCompatNow(out KnownGoodPalworld known)
        {
            known = LoadKnownGood();
            var det = DetectPalworldVersion();
            string manifestHash = ReadManifestCombinedHash();
            return PalworldCompat.Evaluate(known, det, manifestHash);
        }

        // 起動時に呼ばれる。acfの読み取りや40GBのpakへのアクセスはディスク次第で
        // 待たされる(ゲームがHDDや外付けにある環境では体感できる)ので、
        // 判定はバックグラウンドで行い、警告が要る時だけUIスレッドで出す。
        //
        // dev#91追記: 版番号が既知と不一致でも、抽出物マニフェスト
        // (vanilla_manifest.json)が既知良好と一致すれば警告しない。しかしmanifestは
        // 起動直後に自動で走るwarm-cache(WarmSharedCacheOnStartup、冷抽出で実測
        // 数十秒〜74秒程度)が完了しないと手に入らない。**アプリの起動自体は
        // 一切ブロックしない**(このメソッドは元々ThreadPool経由の別スレッド実行
        // だったが、最大5分ブロックしうる待ちをThreadPoolに乗せるとプール枯渇の
        // リスクがあるため、専用のバックグラウンドThreadへ切り替えた)。
        // 待った上でも駄目なら従来どおり警告する(Blender未セットアップ等で
        // warm-cacheが動けない場合の出口でもある)。
        void CheckPalworldVersionOnce()
        {
            var thread = new System.Threading.Thread(delegate ()
            {
                KnownGoodPalworld known;
                PalworldCompatStatus st;
                try { st = EvaluateCompatNow(out known); }
                catch (Exception) { return; }    // 確認に失敗しても本体の動作は一切変えない
                if (!st.Detected || !st.ShouldWarn) return;

                if (!st.ManifestAvailable)
                {
                    const int pollIntervalMs = 3000;
                    const int timeoutMs = 5 * 60 * 1000;   // 5分(冷抽出の実測に十分な余裕)
                    int waited = 0;
                    while (waited < timeoutMs)
                    {
                        System.Threading.Thread.Sleep(pollIntervalMs);
                        waited += pollIntervalMs;
                        try { st = EvaluateCompatNow(out known); }
                        catch (Exception) { break; }
                        if (!st.ShouldWarn || st.ManifestAvailable) break;
                    }
                }
                if (!st.ShouldWarn) return;

                PostToUi(delegate
                {
                    AppendLog("Warning: the detected Palworld version differs from the verified "
                        + "version (" + PalworldCompat.FormatDetected(st) + ", supported: "
                        + PalworldCompat.FormatSupported(known) + ") — you can continue");
                    MessageBox.Show(this,
                        TF("MsgPalworldVersionMismatchFormat",
                            PalworldCompat.FormatSupported(known), PalworldCompat.FormatDetected(st)),
                        T("TitlePalworldVersionCheck"),
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
                });
            });
            thread.IsBackground = true;
            thread.Name = "PalworldCompatCheck";
            thread.Start();
        }

        // ---------------- dev#15: 更新通知(セルフアップデートは対象外) ----------------
        // 起動時に配布基盤のversions.jsonを非同期取得し、latestがToolVersionより新しい
        // 時だけ控えめなラベルで知らせる。RunBackground()を使わないのは意図的:
        // RunBackground()は失敗をSetBackgroundError()経由でステータス行・ログへ出すが、
        // ここは「取得失敗はいかなるエラー表示・例外にもならないこと」(聖域)が要件なので、
        // 例外は本メソッド内で完全に握りつぶして戻るだけにする(ログにすら残さない)。
        void CheckForUpdateOnStartup()
        {
            System.Threading.ThreadPool.QueueUserWorkItem(delegate
            {
                string latest;
                string json;
                try
                {
                    ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
                    var req = (HttpWebRequest)WebRequest.Create(VersionCheckUrl);
                    req.Method = "GET";
                    req.UserAgent = "Uchinoko-UpdateCheck/" + ToolVersion.TrimStart('v');
                    // 「タイムアウト数秒」「オフラインで一切邪魔しない」要件のため短めに固定
                    req.Timeout = 4000;
                    req.ReadWriteTimeout = 4000;
                    using (var resp = (HttpWebResponse)req.GetResponse())
                    using (var sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                    {
                        json = sr.ReadToEnd();
                    }
                    latest = JsonStr(json, "latest");
                    // dev#89: 同じ取得の中で"palworld_known_good"ブロックも拾っておく
                    // (存在しなくてもnullのまま=同梱データのみで判定、無害)。
                    // "latest"の有無とは独立の任意フィールドなので、下のlatest早期returnより
                    // 前でキャッシュする(バージョン更新が無い時でも既知良好リストは拡張したい)
                    string kg = JsonObj(json, "palworld_known_good");
                    if (kg != null) remoteKnownGoodJson = kg;
                }
                catch (Exception)
                {
                    return;   // オフライン・DNS失敗・タイムアウト等はすべて無音で諦める
                }
                if (string.IsNullOrEmpty(latest)) return;
                if (!IsNewerVersion(latest, ToolVersion)) return;   // 同じ/古い/解析不能なら何も出さない
                string shownVersion = latest;
                // FIX38(2026-07-31): 以前はここでversions[]配列から対象エントリ
                // (url/sha256/size/filename)を引き、アプリ内ダウンロードに使っていた
                // (dev#216 WP1)。ダウンロード経路自体を削除したため、この抽出はもう
                // 不要(通知は「新版がある」ことと配布ページへの誘導のみで足りる)。
                PostToUi(delegate { ShowUpdateNotice(shownVersion); });
            });
        }

        // "latest"は確認値"2.0.0"(vプレフィックス無し)/ ToolVersionは"v2.0.0"(プレフィックス有り)
        // という実測差があるため、両者とも先頭の v/V を吸収してから数値比較する。
        // プレリリース表記(-beta等)は仕様上考慮不要なので、数字とドットの並びだけを見る。
        // 解析できなければnullを返し、呼び出し側は「不正な文字列」として何もしない扱いにする
        static int[] ParseVersion(string v)
        {
            if (string.IsNullOrEmpty(v)) return null;
            string s = v.Trim();
            if (s.Length > 0 && (s[0] == 'v' || s[0] == 'V')) s = s.Substring(1);
            var m = Regex.Match(s, @"^[0-9]+(\.[0-9]+)*");
            if (!m.Success || m.Value.Length == 0) return null;
            string[] parts = m.Value.Split('.');
            var nums = new int[parts.Length];
            for (int i = 0; i < parts.Length; i++)
            {
                int n;
                if (!int.TryParse(parts[i], NumberStyles.None, CultureInfo.InvariantCulture, out n))
                    return null;
                nums[i] = n;
            }
            return nums;
        }

        // latestがcurrentより真に新しい(semver的な各桁の数値比較。足りない桁は0扱い)場合のみtrue。
        // 同じ/古い/どちらかが解析不能ならfalse(=呼び出し側は何もしない)
        static bool IsNewerVersion(string latest, string current)
        {
            int[] a = ParseVersion(latest);
            int[] b = ParseVersion(current);
            if (a == null || b == null) return false;
            int len = Math.Max(a.Length, b.Length);
            for (int i = 0; i < len; i++)
            {
                int av = i < a.Length ? a[i] : 0;
                int bv = i < b.Length ? b[i] : 0;
                if (av != bv) return av > bv;
            }
            return false;
        }

        // UIスレッド専用。ラベルに新版を出す(通知は控えめに、ダイアログは出さない)。
        // latestVersionは配布基盤の実測値どおり"2.0.0"(vプレフィックス無し)を想定するが、
        // 将来"v2.1.0"形式に変わっても二重表示("vv2.1.0")にならないよう吸収する
        // FIX38(2026-07-31): 以前はentryOrNull引数(versions.jsonのversions[]から引いた
        // url/sha256/size/filename)を取り、完全なエントリが引けた時だけ「今すぐ更新」
        // ボタンを表示していた(dev#216 WP1)。ボタンはもうダウンロードせず配布ページを
        // 開くだけなので、その絞り込みは不要になった。updateLabelと同じ条件で常に出す。
        void ShowUpdateNotice(string latestVersion)
        {
            // dev#173: 言語切替時にApplyLanguage()から再呼び出しして文言だけ差し替える
            // ため、直近に表示した版番号を憶えておく
            pendingUpdateVersion = latestVersion;
            string display = latestVersion.Length > 0 && (latestVersion[0] == 'v' || latestVersion[0] == 'V')
                ? latestVersion
                : "v" + latestVersion;
            updateLabel.Text = TF("UpdateNoticeFormat", display);
            updateLabel.Visible = true;
            updateNowButton.Visible = true;
            updateNowButton.Enabled = true;
        }

        // 既定ブラウザでBOOTH新店ページを開く。失敗しても無音(通知クリックの延長で
        // 二重にエラーダイアログを出す必要は無い)。FIX38(2026-07-31): 「今すぐ更新」
        // ボタンからも同じメソッドを呼ぶよう変更した(旧: アプリ内DL・検証・展開、
        // FIX36参照)。
        void OpenUpdateDownloadPage()
        {
            try { Process.Start(new ProcessStartInfo(UpdateDownloadPageUrl) { UseShellExecute = true }); }
            catch (Exception) { }
        }

        // 照合はバックグラウンドで走るので、その最中にユーザーが「Palworldに適用」
        // (上書きコピー)や「MODを解除」(削除)を押すことがある。共有指定を緩めて
        // おかないと、そちらが「他のプロセスが使用中」で失敗してしまう。
        // 読んでいる途中で差し替えられた場合の結果は世代番号(appliedStatusGen)で
        // 捨てられるため、誤った表示は残らない
        string Sha1File(string path)
        {
            using (var sha = System.Security.Cryptography.SHA1.Create())
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read,
                                           FileShare.ReadWrite | FileShare.Delete))
            {
                return BitConverter.ToString(sha.ComputeHash(fs));
            }
        }

        List<string[]> BuiltPaks()  // {path, avatarName}
        {
            var result = new List<string[]>();
            if (!Directory.Exists(workRoot)) return result;
            foreach (string jobDir in Directory.GetDirectories(workRoot))
            {
                string buildDir = Path.Combine(jobDir, "build");
                if (!Directory.Exists(buildDir)) continue;
                foreach (string pak in Directory.GetFiles(buildDir, "*_PlayerSwap_P.pak"))
                    result.Add(new string[] { pak, Path.GetFileName(jobDir) });
            }
            return result;
        }

        void RefreshPakList()
        {
            pakList.Items.Clear();
            foreach (var entry in BuiltPaks())
            {
                var fi = new FileInfo(entry[0]);
                var item = new ListViewItem(new string[] {
                    entry[1], fi.Name,
                    string.Format("{0:F1} MB", fi.Length / 1048576.0),
                    fi.LastWriteTime.ToString("yyyy/MM/dd HH:mm") });
                item.Tag = entry[0];
                pakList.Items.Add(item);
            }
            UpdateAppliedStatus();
        }

        // 「今ゲームに入っているMODはどれか」の表示。
        // 中身の照合はpak(数百MB)のSHA1なので数秒かかる ← 起動時にウィンドウごと
        // 固まっていた正体。ファイルの有無で決まるところ(removeButtonの可否、
        // 旧名からの引き継ぎ)までは即座にUIスレッドで確定させ、
        // 時間のかかる照合だけをバックグラウンドへ出して、終わったら表示を差し替える。
        void UpdateAppliedStatus()
        {
            int gen = ++appliedStatusGen;   // 走っている古い照合の結果は無効になる
            string paks = PaksDir();
            if (paks == null) { appliedLabel.Text = T("AppliedStatusNoPaksDir"); return; }
            string target = Path.Combine(paks, InstallName);
            // 旧名で入っていたら新名扱いに引き継ぐ(改名の移行措置。旧2世代とも対象)
            foreach (string legacyName in LegacyInstallNames)
            {
                string legacy = Path.Combine(paks, legacyName);
                if (!File.Exists(target) && File.Exists(legacy))
                {
                    try { File.Move(legacy, target); } catch (Exception) { target = legacy; }
                }
            }
            bool anyLegacyLeft = false;
            foreach (string legacyName in LegacyInstallNames)
                if (File.Exists(Path.Combine(paks, legacyName))) { anyLegacyLeft = true; break; }
            removeButton.Enabled = File.Exists(target) || anyLegacyLeft;
            if (!File.Exists(target)) { appliedLabel.Text = T("AppliedStatusNone"); return; }
            long targetLen;
            try { targetLen = new FileInfo(target).Length; }
            catch (Exception) { appliedLabel.Text = T("AppliedStatusUnknownMod"); return; }
            // 一覧(ListView)はUIスレッドからしか読めないので、ここで材料を写し取る
            var candidates = new List<string[]>();   // {pakのパス, アバター名}
            foreach (ListViewItem item in pakList.Items)
                candidates.Add(new string[] { (string)item.Tag, item.SubItems[0].Text });
            appliedLabel.Text = T("AppliedStatusChecking");
            string targetPath = target;
            RunBackground(T("WhatAppliedModCheck"), delegate
            {
                string name;
                try { name = IdentifyAppliedPak(targetPath, targetLen, candidates); }
                catch (Exception ex)
                {
                    // 照合中にMODが差し替えられた/消された等。その操作で世代が
                    // 進んでいるなら、この失敗はもう用済みなので捨てる。
                    // まだ現役なら握りつぶさずに見せる
                    PostToUi(delegate
                    {
                        if (gen != appliedStatusGen) return;
                        appliedLabel.Text = T("AppliedStatusCheckFailed");
                        SetBackgroundError(T("WhatAppliedModCheck"), ex);
                    });
                    return;
                }
                PostToUi(delegate
                {
                    // 確認中に適用/解除/一覧更新が入っていたら、この結果は捨てる
                    if (gen != appliedStatusGen) return;
                    appliedLabel.Text = name != null
                        ? TF("AppliedStatusNamedFormat", name)
                        : T("AppliedStatusUnknownMod");
                });
            });
        }

        // ワーカースレッド側。判定ロジックは従来と同一(サイズが一致するものだけ
        // ハッシュを取り、targetのハッシュは必要になった時に一度だけ計算する)
        string IdentifyAppliedPak(string target, long targetLen, List<string[]> candidates)
        {
            string hash = null;
            foreach (string[] c in candidates)
            {
                var src = new FileInfo(c[0]);
                if (!src.Exists || src.Length != targetLen) continue;
                if (hash == null) hash = Sha1File(target);
                if (Sha1File(src.FullName) == hash) return c[1];
            }
            return null;
        }

        // 2026-07-26 LX追加: Palworldフォルダへの書き込み/削除失敗を、.NET例外の
        // 生メッセージのままユーザーに見せない。オーナー実機(Windows Sandbox)で
        // "Access to the path '...' is denied." がそのまま出て「エラーが優しくない」と
        // 指摘された。非エンジニア(BOOTHで買った人)は英語の例外文を見ても
        // 次に何をすればいいか分からない。
        // 例外の型で原因を大まかに分類し、①原因 ②対処 を短く示す。
        // 元の例外メッセージ・適用先パスは削らず、ダイアログには要約だけを出しつつ、
        // 全文は必ずAppendLog経由でログ欄・セッションログ(「ログをコピー」)に残す
        // (診断情報を減らさない。CLAUDE.mdの「無言の打ち切り禁止」と同じ考え方)。
        // 事前チェック(書き込めるかを先に試す等)は追加していない: 誤判定で正常な
        // 適用/解除まで止めるリスクの方が大きいと判断したため(本日、別班の早期検査が
        // 誤判定を2回起こしている)。実際にコピー/削除を試みて、失敗した"結果"だけを
        // 元にメッセージを出す設計に留めた
        void ShowApplyFailure(string actionLabel, string targetPath, Exception ex)
        {
            string cause, action;
            if (ex is UnauthorizedAccessException)
            {
                cause = T("CauseNoWritePermission");
                action = T("ActionNoWritePermission");
            }
            else if (ex is IOException && ((uint)ex.HResult == 0x80070070 || (uint)ex.HResult == 0x80070027))
            {
                // ERROR_DISK_FULL(0x70)/ERROR_HANDLE_DISK_FULL(0x27)。メッセージ文言は
                // OSのUI言語で変わりうるため、文字列一致ではなくHResultで判定する
                cause = T("CauseDiskFull");
                action = T("ActionDiskFull");
            }
            else if (ex is IOException)
            {
                cause = T("CauseFileInUse");
                action = T("ActionFileInUse");
            }
            else if (ex is DirectoryNotFoundException || ex is DriveNotFoundException)
            {
                cause = T("CauseTargetFolderNotFound");
                action = T("ActionTargetFolderNotFound");
            }
            else
            {
                cause = T("CauseUnexpected");
                action = T("ActionUnexpected");
            }
            AppendLog("[エラー] " + actionLabel + "に失敗: " + targetPath
                + " / [" + ex.GetType().Name + "] " + ex.Message);
            MessageBox.Show(
                TF("MsgApplyFailureBodyFormat", actionLabel, cause, action, targetPath),
                TF("MsgApplyFailureTitleFormat", actionLabel));
        }

        void ApplySelected()
        {
            if (pakList.SelectedItems.Count == 0)
            {
                MessageBox.Show(T("MsgSelectModFromList"));
                return;
            }
            if (IsGameRunning())
            {
                MessageBox.Show(T("MsgGameRunningApply"));
                return;
            }
            string paks = PaksDir();
            if (paks == null) return;
            string src = (string)pakList.SelectedItems[0].Tag;
            if (!File.Exists(src)) { MessageBox.Show(TF("MsgModFileNotFoundFormat", src)); RefreshPakList(); return; }
            string applyTarget = Path.Combine(paks, InstallName);
            try
            {
                File.Copy(src, applyTarget, true);
                // 旧名の残骸があれば二重適用にならないよう消す(旧2世代とも)
                foreach (string legacyName in LegacyInstallNames)
                {
                    string legacy = Path.Combine(paks, legacyName);
                    if (File.Exists(legacy)) File.Delete(legacy);
                }
            }
            catch (Exception ex)
            {
                ShowApplyFailure(T("LabelApply"), applyTarget, ex);
                return;
            }
            UpdateAppliedStatus();
            string applied = pakList.SelectedItems[0].SubItems[0].Text;
            statusLabel.Text = TF("StatusAppliedFormat", applied);
            MessageBox.Show(TF("MsgApplySuccessFormat", applied), T("TitleApplySuccess"));
        }

        void DeleteSelected()
        {
            if (pakList.SelectedItems.Count == 0) return;
            string pak = (string)pakList.SelectedItems[0].Tag;
            string avatar = pakList.SelectedItems[0].SubItems[0].Text;
            string jobDir = Path.GetDirectoryName(Path.GetDirectoryName(pak));

            // UEプロジェクトはjob.jsonの記載を正とするが、誤爆防止のため
            // このツールの ue_project\ 配下にある場合だけ削除対象にする
            string ueProjDir = null;
            string jobJson = Path.Combine(jobDir, "job.json");
            if (File.Exists(jobJson))
            {
                string uepro = JsonStr(File.ReadAllText(jobJson, Encoding.UTF8), "ue_project");
                if (uepro != null)
                {
                    string root = Path.Combine(appRoot, "ue_project");
                    string cand = Path.GetDirectoryName(uepro);  // ...\<名前>\Pal
                    if (cand != null && cand.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                        ueProjDir = Path.GetDirectoryName(cand); // ...\<名前>
                }
            }

            var sb = new StringBuilder();
            sb.AppendLine(TF("ConfirmDeleteHeaderFormat", avatar));
            sb.AppendLine();
            sb.AppendLine(TF("LineModFileFormat", Path.GetFileName(pak)));
            sb.AppendLine(TF("LineWorkFolderFormat", jobDir));
            if (ueProjDir != null && Directory.Exists(ueProjDir))
                sb.AppendLine(TF("LineUeProjectFormat", ueProjDir));
            sb.AppendLine();
            sb.AppendLine(T("NoteVrmNotDeleted"));
            sb.AppendLine(T("NoteReloadVrmToRedo"));
            if (MessageBox.Show(sb.ToString(), T("TitleConfirmDelete"),
                    MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
                return;

            try
            {
                // このツールが作った生成物を全部消す(work\<名前>ごと+UEプロジェクト)。
                // 元のVRMはツールの外にあるので無傷
                if (Directory.Exists(jobDir)) Directory.Delete(jobDir, true);
                if (ueProjDir != null && Directory.Exists(ueProjDir))
                    Directory.Delete(ueProjDir, true);
            }
            catch (Exception ex)
            {
                MessageBox.Show(TF("MsgDeleteFailedFormat", ex.Message));
            }
            // 「最後に開いたVRM」の記憶がこのアバターなら忘れる
            // (残すと次回起動時に勝手に読み込んで作業フォルダが復活してしまう)
            try
            {
                string f = LastVrmFile();
                if (File.Exists(f))
                {
                    string last = File.ReadAllText(f, Encoding.UTF8).Trim();
                    if (SanitizeName(Path.GetFileNameWithoutExtension(last)) == avatar)
                        File.Delete(f);
                }
            }
            catch (Exception) { }
            // 削除したのが今開いているアバターなら、表示も初期化する
            string current = SanitizeName(Path.GetFileNameWithoutExtension(vrmBox.Text.Trim()));
            if (current == avatar)
            {
                vrmBox.Text = "";
                previewFront.Image = null;
                previewSide.Image = null;
                licenseConfirmed = false;
            }
            RefreshPakList();
            UpdateButtonStates();
            statusLabel.Text = TF("StatusDeletedFormat", avatar);
        }

        // ---------------- 問い合わせ/ログコピー/UEチェック ----------------
        // (旧ShowContact()は廃止: 2026-07-28 オーナー裁定でメインUIのボタンを
        //  「問合せ」1つに統合。dev#42(2026-07-29官能検査是正)で画面から
        //  メールアドレス・GitHub Issues URLの表示を廃止し、2段フロー
        //  (説明→編集可能な送信内容の確認)に改めた。詳細はShowSupportDialog()参照)

        // 2026-07-26 LX追加: sessionLogをそのまま貼ると、同じアバターで何度も
        // 変換をやり直した場合などに際限なく育つ恐れがある(通常の「フル変換」
        // 1回だけでも実測5万〜9万文字あるため、上限は低くしすぎない)。
        // SessionLogCharsを超えたら「先頭(古い方)」を切り捨て、「末尾(直近)」を残す。
        // 優先度を末尾にした理由: ユーザーが今困っている症状は、そのセッションの
        // 最後にやった操作(たいてい最後の変換)に紐づくことがほとんどで、
        // 古い試行錯誤の記録より価値が高いと判断したため。切り捨てた場合は
        // その旨を必ずログ自身に明記する(無言の打ち切りはしない)
        string GetCappedSessionLog()
        {
            string text = sessionLog.ToString();
            if (text.Length == 0) return "(no conversion executed in this session)";
            if (text.Length <= SessionLogCapChars) return text;
            int cut = text.Length - SessionLogCapChars;
            string tail = text.Substring(cut);
            return string.Format(
                "[Note: log was too long, truncated the first (oldest) {0} characters. " +
                "Showing the most recent {1} characters below]\r\n\r\n{2}",
                cut, SessionLogCapChars, tail);
        }

        // 2026-07-26 LX追加: Environment.OSVersion.VersionStringは.NET Frameworkの
        // 互換シムの影響で、app.manifestでWin10/11対応を宣言しない限り
        // "Microsoft Windows NT 6.2.9200.0"(Windows 8相当)に固定されてしまい、
        // Windows 8.1でも11でも同じ値になる(実機で確認済みの症状)。
        // レジストリのCurrentVersionキーから実際のビルド番号を直接読むことで、
        // マニフェスト変更なしに実OSを見分けられるようにする
        // (pipeline\cli\convert.ps1が環境情報ヘッダで既にやっている手口と同じ発想)。
        string GetOsDescription()
        {
            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Windows NT\CurrentVersion"))
                {
                    if (key != null)
                    {
                        object productName = key.GetValue("ProductName");
                        object buildNumber = key.GetValue("CurrentBuildNumber");
                        if (productName != null && buildNumber != null)
                        {
                            string name = productName.ToString();
                            int build;
                            // ビルド22000以降=Windows 11というのは公知の判定基準。
                            // レジストリのProductNameは更新されず"Windows 10"のまま
                            // 残っている環境があるための補正
                            if (int.TryParse(buildNumber.ToString(), out build) && build >= 22000
                                && name.IndexOf("Windows 10", StringComparison.OrdinalIgnoreCase) >= 0)
                            {
                                name = name.Replace("Windows 10", "Windows 11");
                            }
                            object ubr = key.GetValue("UBR");
                            object displayVersion = key.GetValue("DisplayVersion") ?? key.GetValue("ReleaseId");
                            string buildStr = buildNumber.ToString() + (ubr != null ? "." + ubr : "");
                            string verStr = displayVersion != null ? " " + displayVersion : "";
                            return name + verStr + " (build " + buildStr + ", " +
                                (Environment.Is64BitOperatingSystem ? "x64" : "x86") + ")";
                        }
                    }
                }
            }
            catch (Exception) { }
            // レジストリが読めない特殊環境向けの保険。互換シムで古く見えることがある値だが、無いよりまし
            return Environment.OSVersion.VersionString + " (registry read failed)";
        }

        // ---------------- dev#260: 配布チャネルの記録 ----------------
        // 背景: BOOTH/itchへは devtools\release.py がビルドするcanonical zip
        // (build\make_dist.ps1)を**同一バイトのまま**手動アップロードしており、
        // 問い合わせが来てもどの配布チャネル経由で入手したユーザーかが
        // 診断ログから一切わからなかった(ZC87VNQX問い合わせで発覚)。
        // 採用した設計(3案比較、詳細はdev#260): canonical zip自体は従来どおり単一のまま
        // 維持し(release.pyのzip内容ゲート・sha256記録に一切影響させない)、各ストアへの
        // アップロード直前に devtools\stamp_channel.py が appRoot直下(ランチャー廃止後は
        // 配布物ルート直下そのもの。旧レイアウトのzip内 _internal\ ではない)へ
        // channel.txt を書き足した**別名の**zipを作る。
        // (注記: devtools\stamp_channel.pyはこの改修の対象外のため
        // 未改修の場合がある。同スクリプトが旧レイアウト前提のまま_internal\へ書き続けている場合、
        // 実際にはchannel.txtが読まれる場所とズレるため追随が必要。
        // fail-closed設計(下記)によりチャネル不明="unknown"に倒れるだけで、
        // アプリの起動・変換自体は損なわれない)
        //   - チャネル別に3zipをビルドする案(a)は release.py のzip内容ゲートを3倍走らせ、
        //     dev#220裁定「リリース10分未満」に反するため却下
        //   - 初回起動時に入手元を尋ねるダイアログ案(c)は、dev#218で類似の初回言語
        //     ポップアップを摩擦低減のため廃止したばかりの方針と矛盾するため却下
        // channel.txtが無い(=旧zip・スタンプ忘れ・非対応の入手経路)場合はfail-closedで
        // "unknown"に倒す(誤ったチャネルを断定するより安全)。
        static readonly string[] KnownDistChannels = { "booth", "itch", "github", "dev" };
        const string UnknownDistChannel = "unknown";

        // 純粋関数(I/Oなし): 生の文字列 -> 既知チャネルの正規化。
        // trimして完全一致でのみ採用する(部分一致はしない)。これにより、
        // 手作業でchannel.txtが壊れた場合(例: 複数行・末尾にゴミ)や、将来追加された
        // 未知の値が紛れ込んだ場合も、誤ったチャネルとして扱わずunknownに倒れる
        // (単体表 CheckDistChannelLogic の負の対照 case7/case8参照)。
        internal static string NormalizeDistChannel(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return UnknownDistChannel;
            string trimmed = raw.Trim().ToLowerInvariant();
            foreach (string known in KnownDistChannels)
            {
                if (trimmed == known) return known;
            }
            return UnknownDistChannel;
        }

        // ファイルI/Oを含むが、パスを外から渡せる形にして単体試験できるようにしてある
        // (--check-path-health の BuildPathFacts と同じ考え方)。読み取り失敗(ファイル無し・
        // 権限エラー等)は例外を握りつぶしてunknownへ倒す(診断ログの他の項目と同じ流儀)。
        internal static string ReadDistChannelFromFile(string filePath)
        {
            try
            {
                if (!File.Exists(filePath)) return UnknownDistChannel;
                return NormalizeDistChannel(File.ReadAllText(filePath, Encoding.UTF8));
            }
            catch (Exception)
            {
                return UnknownDistChannel;
            }
        }

        // appRoot直下の channel.txt を読む。settings_*.txt(ユーザー設定、アプリ自身が
        // 書き込む)とは異なり、こちらは配布側(devtools\stamp_channel.py)が
        // パッケージング時にのみ書く読み取り専用のマーカーで、アプリは一切書き込まない
        string ReadDistChannel()
        {
            return ReadDistChannelFromFile(Path.Combine(appRoot, "channel.txt"));
        }

        internal static bool CheckDistChannelLogic(out List<string> problems)
        {
            problems = new List<string>();

            // case1-4: 既知チャネルはそのまま採用(大文字小文字・前後空白を許容)
            if (NormalizeDistChannel("booth") != "booth") problems.Add("case1(booth): normalize failed");
            if (NormalizeDistChannel("  ITCH  \r\n") != "itch") problems.Add("case2(ITCH, mixed case+whitespace): normalize failed");
            if (NormalizeDistChannel("GitHub") != "github") problems.Add("case3(GitHub, mixed case): normalize failed");
            if (NormalizeDistChannel("dev") != "dev") problems.Add("case4(dev): normalize failed");

            // case5/6(負の対照): 空・nullはunknownへ倒れること
            if (NormalizeDistChannel("") != UnknownDistChannel) problems.Add("case5(empty string): expected unknown");
            if (NormalizeDistChannel(null) != UnknownDistChannel) problems.Add("case6(null): expected unknown");

            // case7(負の対照): 既知の語彙に無い値を断定してはいけない(手作業ミス・将来の
            // 新チャネル追加漏れ等で誤ったラベルが付くのを防ぐ)
            if (NormalizeDistChannel("steam") != UnknownDistChannel) problems.Add("case7(unknown value 'steam'): expected unknown, must not pass through");

            // case8(負の対照): 部分一致で誤採用しないこと(channel.txtが壊れた場合の保険)
            if (NormalizeDistChannel("booth\nextra garbage") != UnknownDistChannel) problems.Add("case8(corrupted multi-line content): expected unknown, must not partial-match");

            // case9(正の対照、ファイルI/O経由): 実在するファイルの内容が正しく反映されること
            string tmpFile = Path.Combine(Path.GetTempPath(), "d2p_channel_check_" + Guid.NewGuid().ToString("N") + ".txt");
            try
            {
                File.WriteAllText(tmpFile, "itch", new UTF8Encoding(false));
                if (ReadDistChannelFromFile(tmpFile) != "itch")
                    problems.Add("case9(file containing 'itch'): expected 'itch'");
            }
            finally
            {
                try { File.Delete(tmpFile); } catch (Exception) { }
            }

            // case10(負の対照、受入条件の核心): マーカーファイルが存在しないzip(=従来の
            // canonical zip・旧バージョン)を読んだ場合、必ずunknownへ安全に倒れること
            string missingFile = Path.Combine(Path.GetTempPath(), "d2p_channel_missing_" + Guid.NewGuid().ToString("N") + ".txt");
            if (ReadDistChannelFromFile(missingFile) != UnknownDistChannel)
                problems.Add("case10(marker file absent, i.e. legacy zip): expected unknown");

            return problems.Count == 0;
        }

        static void CheckDistChannelCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckDistChannelLogic(out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== dist channel logic unit table (dev#260) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "dist_channel_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "DIST_CHANNEL_CHECK_OK" : "DIST_CHANNEL_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // ---------------- dev#7: SanitizeForClipboardの単体表 ----------------
        // 実ユーザー報告4AL4M4GT(非%USERPROFILE%ドライブの絶対パス漏洩)を受けた三段構成
        // (work\issue_zero\i7\NOTES.md)の最終防衛段の検査。--check-i18n等と同じ「隠しCLI+
        // internal static純粋関数」パターンを使う(実exeをビルドして検査。dev#7の監査コメントが
        // 言及していた「Harness.cs(リフレクション経由)」は実在せず未実装だったため、
        // 既存の確立パターンに倣った)。
        // フィクスチャは全て架空の値(実在の個人情報は使わない)。
        internal static bool CheckSanitizeForClipboardLogic(out List<string> problems)
        {
            problems = new List<string>();

            // case1(正の対照、既存機能の無退行): %USERPROFILE%配下はこれまでどおり
            // トークン化される
            string up = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            string underUp = Path.Combine(up, "Downloads", "avatar.vrm");
            string r1 = SanitizeForClipboard("input: " + underUp);
            if (!r1.Contains("%USERPROFILE%") || r1.Contains(up))
                problems.Add("case1(%USERPROFILE%配下): トークン化されない、または生パスが残った: " + r1);

            // case2(正の対照、既存機能の無退行): SteamID64
            string r2 = SanitizeForClipboard("steamid: 76561198012345678");
            if (!r2.Contains("<SteamID>") || r2.Contains("76561198012345678"))
                problems.Add("case2(SteamID64): マスクされない: " + r2);

            // case3(正の対照、既存機能の無退行): アカウント名の単語境界一致
            string userName = Environment.UserName;
            if (!string.IsNullOrEmpty(userName) && userName.Length > 3)
            {
                string r3 = SanitizeForClipboard("path fragment: xxx-" + userName + "-yyy has " + userName + " alone");
                if (!r3.Contains("<user>") || r3.Contains(userName))
                    problems.Add("case3(ユーザー名の保険置換): マスクされない: " + r3);
            }

            // case4(核心、dev#7): 非%USERPROFILE%ドライブの絶対パス。実ユーザー報告
            // 4AL4M4GTの実例(Unity/VCCのインストール先・Steamライブラリ)を模した架空の
            // フィクスチャ(実在の個人情報は使わない)。旧実装はこれを一切マスクせず
            // 素通りしていた
            const string fakeUserFolder = "D:\\Users\\SampleTaro\\UnityProjects\\MyAvatarProject\\Assets\\avatar.prefab";
            string r4 = SanitizeForClipboard("Unity project: " + fakeUserFolder);
            if (r4.Contains(fakeUserFolder) || r4.Contains("SampleTaro"))
                problems.Add("case4(非UserProfileドライブの絶対パス、核心): 生パスまたはユーザー名が残った: " + r4);
            // case4b(診断可用性): マスク後も原因切り分けに使える拡張子情報は残ること
            if (!r4.Contains("ext=.prefab"))
                problems.Add("case4b(伏字化後の診断可用性): 拡張子(.prefab)の情報が失われた: " + r4);

            // case5(核心、dev#7): UNCパスも同様に非UserProfileの絶対パスとして漏れうる
            const string fakeUncPath = "\\\\BUILDSERVER\\share\\SampleHanako\\SteamLibrary\\steamapps\\common\\Palworld\\Pal-Windows.pak";
            string r5 = SanitizeForClipboard("Palworld pak: " + fakeUncPath);
            if (r5.Contains(fakeUncPath) || r5.Contains("SampleHanako"))
                problems.Add("case5(UNCパス): 生パスまたはユーザー名が残った: " + r5);

            // case6(負の対照): パスに見えない通常の文章・URLはマスクされず読めるままであること
            // (誤検知で診断本文を過剰に壊さないことの確認。"C:"のような単独ドライブ文字は
            // バックスラッシュを伴わないためマッチしない)
            string plain = "status: converting avatar, see https://example.com/help for C: drive info";
            string r6 = SanitizeForClipboard(plain);
            if (!r6.Contains("https://example.com/help"))
                problems.Add("case6(誤検知しないこと): 無関係な文字列まで壊れた: " + r6);

            // case7(負の対照、受入条件の核心): 空文字列・nullを渡しても例外にならないこと
            if (SanitizeForClipboard("") != "") problems.Add("case7a(空文字列): 空文字列以外を返した");
            if (SanitizeForClipboard(null) != null) problems.Add("case7b(null): nullを返さなかった");

            return problems.Count == 0;
        }

        static void CheckSanitizeForClipboardCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckSanitizeForClipboardLogic(out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== SanitizeForClipboard logic unit table (dev#7) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "sanitize_clipboard_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "SANITIZE_CLIPBOARD_CHECK_OK" : "SANITIZE_CLIPBOARD_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // 診断ログ本文の組み立て。「ログを手動でコピー」と「問合せ」(dev#25/dev#42)で共用する。
        // 戻り値は**未伏字**。呼び出し元は外へ出す直前(クリップボード/送信ペイロード)で
        // 必ず SanitizeForClipboard() を通すこと(画面表示・ログファイルには適用しない方針のため)
        string BuildDiagnosticsText()
        {
            var sb = new StringBuilder();
            sb.AppendLine("--- Uchinoko for Palworld Bug Report Log ---");
            sb.AppendLine("version: " + ToolVersion);
            // dev#260: どの配布チャネル(booth/itch/github/dev/unknown)経由の入手かを記録。
            // 「os:」等と同じく技術ログ行(非翻訳、言語問わず固定英語ラベル)
            sb.AppendLine("channel: " + ReadDistChannel());
            sb.AppendLine("date: " + DateTime.Now.ToString("yyyy-MM-dd HH:mm"));
            sb.AppendLine("os: " + GetOsDescription());
            // dev#87追記2(2026-07-29 コーディネーター指示): 表示に使っているUI言語と
            // OSロケールの両方を残す。目的は環境依存バグの診断ではなく、問い合わせ者
            // 本人の言語でサポート返信するため(judged by GetOsDescription()と違い、
            // これ自体は機体固有情報ではなく単なる表示設定+OSロケールなので毎回軽い)
            sb.AppendLine("lang: " + LangToCode(Strings.Current) + " (ui) / "
                + CultureInfo.CurrentUICulture.Name + " (os)");
            sb.AppendLine("avatar: " + (vrmBox.Text.Trim().Length > 0
                ? Path.GetFileName(vrmBox.Text.Trim()) : "(not selected)"));
            // dev#87(wp878991): 検出Palworld版・動作確認済み版の両方を必ず数字入りで
            // 残す(検出失敗時も"not found"の事実を残す)。EvaluateCompatNow()は
            // CheckPalworldVersionOnce()と同じ判定基準を使う共通経路(小さいファイル
            // 読み取りのみ、ネットワークアクセスなし・待ちなしで軽い)
            try
            {
                KnownGoodPalworld pcKnown;
                PalworldCompatStatus pcStatus = EvaluateCompatNow(out pcKnown);
                sb.AppendLine(PalworldCompat.BuildLogLine(pcKnown, pcStatus));
            }
            catch (Exception ex)
            {
                sb.AppendLine("palworld: check failed (" + ex.Message + ")");
            }
            sb.AppendLine(OtherPakSummaryLine());   // dev#98/#103
            sb.AppendLine("status: " + statusLabel.Text);
            sb.AppendLine("--- Execution Log (all work on this avatar, including across process steps) ---");
            // dev#42b(2026-07-29構造修正): 「ログが変わったか」の比較(ShowSupportDialog参照)は
            // このメソッドの戻り値をそのまま==比較するのではなく、NormalizeLogForComparison()を
            // 両辺に通してから比較すること。理由はこの関数の直下(NormalizeLogForComparisonの
            // コメント)を参照
            sb.AppendLine(GetCappedSessionLog());
            return sb.ToString();
        }

        // dev#42b(2026-07-29構造修正・コーディネーター指示): 「送信済み後にログが
        // 変わったか」の比較(ShowSupportDialog参照)専用の正規化。
        // BuildDiagnosticsText()の戻り値には「実行するたびに必ず変わるが、それ自体は
        // 情報価値の無い行」が混じっており、素の文字列比較では実質どんな2回の呼び出しも
        // 不一致になってしまう。ここで除外するのはそうした行**だけ**であり、実際の状態
        // 変化(バージョン更新・アバター切替・UE検出状況・status・実行ログ本文の追加や
        // エラー等)を反映する行は絶対に除外しない(除外し過ぎると「変化したのに未検知」
        // という逆方向の事故になるため)。
        //
        // 現時点で除外するのは次の1行のみ:
        //   - "date: " 行 … DateTime.Now を分単位で埋め込むため、1分でも経てば
        //     内容と無関係に必ず変わる。実質的な情報(バージョン・アバター・状態・
        //     実行ログ)は他の行に既に出ているため、この行だけを比較対象から外しても
        //     「本当に何かが変わった」の検知能力は落ちない。
        //
        // 除外しなかった(=検討したが除外すべきでないと判断した)行:
        //   - "version: " … ツールのバージョン更新は利用者が気づいてほしい実変化
        //   - "os: "      … レジストリ直読みで機体固有・毎回同一値(GetOsDescription参照)。
        //     実行毎に変わらないため、比較上は元々ノイズにならない
        //   - "lang: "    … UI言語切替(次回起動反映)・OSロケールの変化。頻度は低いが
        //     実変化なので除外しない(dev#87追記2)
        //   - "avatar: "  … 選択アバターの切替は明確に意味のある変化
        //   - "palworld: " … 検出Palworld版・自己判定結果の変化は意味のある変化
        //     (dev#87/#91。版アップデートやmanifest自己判定の完了タイミングで変わりうる)
        //   - "other_paks: " … 他MODの追加/削除は実環境の変化そのもの(dev#98/#103)。
        //     ユーザーが手動でPaksフォルダを弄らない限り変化しないためノイズにもならない
        //   - "status: "  … 画面のステータス文言。変換の進行等、実際の状態変化を表すため保持
        //   - 実行ログ本文(GetCappedSessionLog) … 工程の追加・エラーはまさに検知したい変化。
        //     ただしMarkSessionStage()が刻む区切り行 "=== ステージ名 (HH:mm:ss) ===" は
        //     工程が実際に切り替わった時にしか追加されないため「毎回必ず変わる行」には
        //     該当しない(=何もしなければ呼び出す回数を増やしても本文自体は増えない)
        static string NormalizeLogForComparison(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;
            string[] lines = text.Replace("\r\n", "\n").Split('\n');
            var sb = new StringBuilder(text.Length);
            foreach (string line in lines)
            {
                if (line.StartsWith("date: ", StringComparison.Ordinal)) continue;
                sb.Append(line).Append('\n');
            }
            return sb.ToString();
        }

        void CopyLogToClipboard()
        {
            try
            {
                // U-log: クリップボードに渡す直前だけサニタイズする(画面表示・ログファイルは元のまま)
                Clipboard.SetText(SanitizeForClipboard(BuildDiagnosticsText()));
                // dev#42 item3: 画面にメール/GitHub Issues案内を出さない方針になったため、
                // 案内文を窓口非依存の中立な表現に変更(コピー自体は引き続き提供する)
                MessageBox.Show(T("MsgLogCopiedBody"), T("TitleLogCopied"));
            }
            catch (Exception ex)
            {
                MessageBox.Show(TF("MsgCopyFailedFormat", ex.Message));
            }
        }

        // ---------------- dev#25/dev#42: 問合せ(診断ログの直接送信) ----------------
        // 「ログを手動でコピー」して手で貼ってもらう代わりに、その場で診断ログを
        // report.osakishokai.com へ送る経路。API契約は work\wp_report\REPORT.md が正:
        //   POST /report  JSON {version, meta?, log_gzip_b64} → {ok, id(8桁英数), view_url}
        //   本文上限5MB(セッションログは50万字上限+gzipなので実際は遠く及ばない)
        // 設計上の注意:
        //   - User-Agentは必ず独自値。既定のUAはゾーンのbot対策で403になることが
        //     実測済み(wp_reportのselftest1.log。Python既定UAで発見された症状)
        //   - 送るのは伏字化(SanitizeForClipboard)済みの診断テキストだけ。
        //     アバターのモデルデータ・ファイル本体は一切送らない
        //   - 送信は明示クリック時のみ(自動送信はしない)。失敗してもエラーで
        //     固めず、従来の「ログを手動でコピー」への案内へ静かに縮退する
        //   - 送信自体はワーカースレッドで行い、UIを固めない
        //   - dev#42(2026-07-29): 送信前に「次の内容が送られます」を編集可能な
        //     形で確認させる2段フローに変更(ShowSupportDialog参照)。ユーザーが
        //     確認画面で本文を編集した場合に備え、BuildReportPayloadJsonへ
        //     本文を外部から渡せるオーバーロードを追加した(下記)

        class ReportSendResult
        {
            public bool Ok;
            public string Id;
            public string ViewUrl;
            public string Error;
        }

        // 送信ペイロード(JSON)の組み立て。vrmBox等のUIを読むためUIスレッドで呼ぶこと。
        // maskedLog には伏字化後のログ本文を返す(試験でのダンプ確認用)。
        // ログ・meta とも、外へ出る文字列はすべて SanitizeForClipboard を通してから詰める。
        // 従来どおり本文をBuildDiagnosticsText()で内部生成する版(CLIの--send-report専用、
        // 無編集本文でよい場合)。GUIの2段フロー(ユーザーが確認画面で編集できる)は
        // 下のオーバーロードを使う
        string BuildReportPayloadJson(out string maskedLog)
        {
            return BuildReportPayloadJson(BuildDiagnosticsText(), out maskedLog);
        }

        // dev#42: 編集済み本文(ShowSupportDialogの確認画面でユーザーが編集した後の
        // テキスト)を外部から渡せる版。渡された本文にも必ずSanitizeForClipboardを
        // 通してから送る(ユーザーの編集漏れに対する保険。伏字化は常に最終防衛線)
        string BuildReportPayloadJson(string logText, out string maskedLog)
        {
            maskedLog = SanitizeForClipboard(logText);
            string os = SanitizeForClipboard(GetOsDescription());
            string avatar = SanitizeForClipboard(vrmBox.Text.Trim().Length > 0
                ? Path.GetFileName(vrmBox.Text.Trim()) : "(未選択)");
            string status = SanitizeForClipboard(statusLabel.Text);
            // dev#260: channelは既知enum{booth,itch,github,dev,unknown}のみを返す
            // NormalizeDistChannel経由の値なので、他フィールドと違いSanitizeForClipboard不要
            // (ユーザー由来の自由文字列を一切含まない)
            string channel = ReadDistChannel();

            byte[] raw = Encoding.UTF8.GetBytes(maskedLog);
            byte[] gz;
            using (var ms = new MemoryStream())
            {
                using (var gzs = new GZipStream(ms, CompressionMode.Compress, true))
                {
                    gzs.Write(raw, 0, raw.Length);
                }
                gz = ms.ToArray();
            }

            var sb = new StringBuilder();
            sb.Append("{\"version\":\"").Append(JsonEscape(ToolVersion)).Append("\",");
            // dev#92残件②: サーバ(d2p-report)は body.lang をトップレベルで見る
            // (index.js: resolveCreateLang(body && body.lang, ...))。新規スレッド作成時に
            // 表示中UI言語を渡すことで、閲覧ページ /r/<id> をUI言語で描画できるようにする
            // (既存スレッドはlang無しのままjaへフォールバックし、壊れない)
            sb.Append("\"lang\":\"").Append(LangToCode(Strings.Current)).Append("\",");
            sb.Append("\"meta\":{");
            sb.Append("\"os\":\"").Append(JsonEscape(os)).Append("\",");
            sb.Append("\"avatar\":\"").Append(JsonEscape(avatar)).Append("\",");
            sb.Append("\"status\":\"").Append(JsonEscape(status)).Append("\",");
            sb.Append("\"channel\":\"").Append(JsonEscape(channel)).Append("\"},");
            sb.Append("\"log_gzip_b64\":\"").Append(Convert.ToBase64String(gz)).Append("\"}");
            return sb.ToString();
        }

        static string JsonEscape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            var sb = new StringBuilder(s.Length + 8);
            foreach (char c in s)
            {
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"': sb.Append("\\\""); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < ' ') sb.AppendFormat("\\u{0:x4}", (int)c);
                        else sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }

        // 実送信。ワーカースレッドから呼んでよい(UIに触らない)。
        // 例外はすべて Error 文字列に落とす(呼び出し元でエラー表示せず縮退案内に使う)
        // appendToId: null/空なら新規 POST /report。指定があれば dev#42b の再送仕様
        // (オーナー裁定「再送は既存スレッドへの追記、別スレッドにしない」)に従い
        // POST /report/<ID>/append を叩く(サーバーは新IDを発行せず同じid/view_urlを返す)。
        // CLIの--send-reportは常にnullを渡し、従来どおり新規POSTのみを行う(挙動不変)。
        static ReportSendResult SendReportPayload(string payloadJson, string appendToId)
        {
            var res = new ReportSendResult();
            try
            {
                // .NET 4.8の既定はSystemDefaultでWin10以降ならTLS1.2が使えるが、
                // 環境設定で古い既定に固定されている保険として明示的に足しておく
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
                string url = string.IsNullOrEmpty(appendToId)
                    ? GetReportBaseUrl() + "/report"
                    : GetReportBaseUrl() + "/report/" + Uri.EscapeDataString(appendToId) + "/append";
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.Method = "POST";
                req.ContentType = "application/json";
                // 独自UA必須(既定UAはbot対策403の実測あり)
                req.UserAgent = "Uchinoko-Support/" + ToolVersion.TrimStart('v');
                req.Timeout = 20000;
                req.ReadWriteTimeout = 20000;
                byte[] body = Encoding.UTF8.GetBytes(payloadJson);
                req.ContentLength = body.Length;
                using (var s = req.GetRequestStream())
                {
                    s.Write(body, 0, body.Length);
                }
                string respText;
                using (var resp = (HttpWebResponse)req.GetResponse())
                using (var sr = new StreamReader(resp.GetResponseStream(), Encoding.UTF8))
                {
                    respText = sr.ReadToEnd();
                }
                var m = Regex.Match(respText, "\"id\"\\s*:\\s*\"([A-Za-z0-9]+)\"");
                if (!m.Success)
                {
                    res.Error = "サーバー応答に報告IDが含まれていません: " +
                        (respText.Length > 200 ? respText.Substring(0, 200) : respText);
                    return res;
                }
                res.Id = m.Groups[1].Value;
                var mv = Regex.Match(respText, "\"view_url\"\\s*:\\s*\"([^\"]+)\"");
                res.ViewUrl = mv.Success
                    ? mv.Groups[1].Value.Replace("\\/", "/")
                    : GetReportBaseUrl() + "/r/" + res.Id;
                res.Ok = true;
            }
            catch (Exception ex)
            {
                res.Error = ex.Message;
            }
            return res;
        }

        // メインUI唯一のサポート導線(2026-07-28 オーナー裁定: ボタンは1つに統合)。
        // dev#42(2026-07-29官能検査是正)でオーナー指定の2段フローに全面改修:
        //   第1段: 説明(送信への同意文言を兼ねる) + [問い合わせフォームを開く]
        //   第2段: 「次の内容が送信されます」+編集可能なログ本文+[OK]
        //   [OK]で編集後の本文を送信し、成功したら view_url を既定ブラウザで開く
        // dev#42b(2026-07-29官能検査是正・再送対応)で追加改訂:
        //   「一度報告すると再度ログを送る方法がない。ログが変わったら再送を原則と
        //   すべき」というオーナー裁定を受け、送信済み後もログの変化を検出して
        //   再送を促す。ただし再送は新規スレッドにせず、前回と同じスレッドへの
        //   追記とする(POST /report/<ID>/append。サーバーは新IDを発行せず、
        //   同じ id/view_url を返す。旧報告はサーバー側に両方残る)。
        //   問合せボタン押下時の分岐:
        //     未送信                                → 第1段
        //     送信済み かつ 現在ログ == 前回送信時ログ → 第3段(送信済み画面)
        //     送信済み かつ 現在ログが変化           → 第2段を直接表示(再送が既定)
        //   第3段にも「ログを再送」ボタンを常設し、変化が無くても手動で再送できる。
        // 画面にはメールアドレス・GitHub Issues URLを一切出さない(dev#42 item3)。
        // 「ログを手動でコピー」は全段で常時押せる(3段のパネルとは別の常設ボタン)。
        // 送信はワーカースレッドなのでUIは固まらない。送信ボタンの無効化は
        // 「その送信処理中」のみで、送信完了後は再送を妨げない(dev#42b item5)。
        void ShowSupportDialog()
        {
            var dlg = new Form();
            dlg.Text = T("BtnReport");
            dlg.FormBorderStyle = FormBorderStyle.FixedDialog;
            dlg.StartPosition = FormStartPosition.CenterParent;
            dlg.MinimizeBox = false;
            dlg.MaximizeBox = false;
            dlg.ClientSize = new Size(520, 340);
            dlg.Icon = TryGetAppIcon();

            // ---- 第1段: 説明 + 開始ボタン ----
            var stage1 = new Panel { Left = 12, Top = 12, Width = 496, Height = 280 };
            var infoLabel = new Label
            {
                Text = T("SupportStage1Info"),
                AutoSize = false, Left = 8, Top = 8, Width = 480, Height = 90,
            };
            var openFormBtn = new Button
            {
                Text = T("BtnOpenInquiryForm"), Left = 8, Top = 106, Width = 240, Height = 34
            };
            stage1.Controls.Add(infoLabel);
            stage1.Controls.Add(openFormBtn);

            // ---- 第2段: 送信内容の確認(編集可能) ----
            // dev#42b: 「変化あり」の場合に上部へ再送を促す注意文を足すため、
            // confirmLabelは可変長(最大4行)を見込んで高さを確保しレイアウトを調整。
            var stage2 = new Panel { Left = 12, Top = 12, Width = 496, Height = 280, Visible = false };
            var confirmLabel = new Label
            {
                Text = "", AutoSize = false, Left = 8, Top = 8, Width = 480, Height = 72,
            };
            var logEditBox = new TextBox
            {
                Left = 8, Top = 84, Width = 480, Height = 136,
                Multiline = true, ScrollBars = ScrollBars.Vertical,
                Font = ResolveLogFont(),
            };
            var okBtn = new Button { Text = T("BtnOk"), Left = 8, Top = 226, Width = 100, Height = 32 };
            var stage2StatusLbl = new Label { Text = "", AutoSize = false, Left = 116, Top = 230, Width = 372, Height = 24 };
            stage2.Controls.Add(confirmLabel);
            stage2.Controls.Add(logEditBox);
            stage2.Controls.Add(okBtn);
            stage2.Controls.Add(stage2StatusLbl);

            // ---- 第3段: 送信済み(いつでも同じ場所を開ける+手動再送) ----
            var stage3 = new Panel { Left = 12, Top = 12, Width = 496, Height = 280, Visible = false };
            var sentLabel = new Label
            {
                Text = "", AutoSize = false, Left = 8, Top = 8, Width = 480, Height = 50,
            };
            var sentUrlBox = new TextBox { Left = 8, Top = 64, Width = 480, Height = 24, ReadOnly = true };
            var openAgainBtn = new Button
            {
                Text = T("BtnOpenSamePlace"), Left = 8, Top = 100, Width = 200, Height = 32
            };
            // dev#42b: ログが不変でも手動で再送できる逃げ道(常設)
            var resendBtn = new Button
            {
                Text = T("BtnResendLog"), Left = 8, Top = 140, Width = 200, Height = 32
            };
            stage3.Controls.Add(sentLabel);
            stage3.Controls.Add(sentUrlBox);
            stage3.Controls.Add(openAgainBtn);
            stage3.Controls.Add(resendBtn);

            // ---- 常設(全段で表示): ログ手動コピー + 閉じる ----
            var copyLogBtn = new Button { Text = T("BtnCopyLogManually"), Left = 12, Top = 300, Width = 160, Height = 28 };
            var closeBtn = new Button
            {
                Text = T("BtnClose"), Left = 396, Top = 300, Width = 112, Height = 28,
                DialogResult = DialogResult.OK,
            };
            copyLogBtn.Click += delegate { CopyLogToClipboard(); };

            Action<string, string> showSentStage = delegate(string id, string url)
            {
                stage1.Visible = false;
                stage2.Visible = false;
                sentLabel.Text = TF("SupportSentLabelFormat", id);
                sentUrlBox.Text = url;
                stage3.Visible = true;
            };

            // dev#42b: 第2段(確認画面)の表示。changedNotice=trueなら「ログが変わっています」
            // 注意文を上部に足す。isAppend=trueなら「(既存スレッドへの)追記」である旨を示す
            // 文言にする(実際に追記になるかどうかはOKクリック時のreportId有無で判定するため、
            // ここは表示文言のみの区別)
            Action<bool, bool> showConfirmStage = delegate(bool changedNotice, bool isAppend)
            {
                logEditBox.Text = BuildDiagnosticsText();
                string notice = changedNotice
                    ? T("SupportChangedNotice")
                    : "";
                string body = isAppend
                    ? T("SupportConfirmAppendBody")
                    : T("SupportConfirmNewBody");
                confirmLabel.Text = notice + body;
                stage1.Visible = false;
                stage3.Visible = false;
                stage2.Visible = true;
                stage2StatusLbl.Text = "";
                okBtn.Enabled = true;
                logEditBox.Enabled = true;
            };

            // ローカル関数はC#5では使えないため、他所と同じ匿名delegate方式に揃える
            Action<string> openUrlInBrowser = delegate(string url)
            {
                try { Process.Start(url); }
                catch (Exception ex) { AppendLog("[report] ページを開けませんでした: " + ex.Message); }
            };

            openFormBtn.Click += delegate { showConfirmStage(false, false); };   // 第1段からの初回送信
            resendBtn.Click += delegate { showConfirmStage(false, true); };      // 第3段からの手動再送(変化不問)

            openAgainBtn.Click += delegate { openUrlInBrowser(sentUrlBox.Text); };

            okBtn.Click += delegate
            {
                string payload;
                string maskedLog;
                string editedLog = logEditBox.Text;
                try
                {
                    payload = BuildReportPayloadJson(editedLog, out maskedLog);
                }
                catch (Exception ex)
                {
                    AppendLog("[report] 送信データの作成に失敗: " + ex.Message);
                    stage2StatusLbl.Text = T("SupportSendFailedUseManualCopy");
                    return;
                }
                // dev#42b: 既にreportIdがあれば「再送=追記」、無ければ「新規」。
                // クリック時点のクラスフィールドをスナップショットして送信先を決める
                // (ワーカースレッド内でクラスフィールドを直接読まないため)
                string appendTargetId = string.IsNullOrEmpty(reportId) ? null : reportId;
                okBtn.Enabled = false;
                logEditBox.Enabled = false;
                stage2StatusLbl.Text = T("SupportSending");
                System.Threading.ThreadPool.QueueUserWorkItem(delegate
                {
                    ReportSendResult res = SendReportPayload(payload, appendTargetId);
                    try
                    {
                        dlg.BeginInvoke((MethodInvoker)delegate
                        {
                            if (res.Ok)
                            {
                                AppendLog("[report] 送信完了 報告ID: " + res.Id + " " + res.ViewUrl);
                                reportId = res.Id;
                                reportViewUrl = res.ViewUrl;
                                // dev#42b: 「その時点のBuildDiagnosticsText()生成結果
                                // (ユーザー編集前の素の文)」を次回の変化検出用に保存する。
                                // editedLog(実際に送った本文)ではなく、いま改めて生成した
                                // 素の文を使うのが仕様(ユーザーの手編集とは独立に判定するため)
                                lastSentBaseLog = BuildDiagnosticsText();
                                showSentStage(res.Id, res.ViewUrl);
                                openUrlInBrowser(res.ViewUrl);   // 成功したら問い合わせフォームを開く
                            }
                            else
                            {
                                // 静かな縮退: エラーで固めず、この場で手動コピー経路を案内。
                                // 失敗理由の詳細はログ欄にだけ残す
                                AppendLog("[report] 送信できませんでした: " + res.Error);
                                stage2StatusLbl.Text = T("SupportSendFailedOffline");
                                okBtn.Enabled = true;   // 回線が戻れば再試行できる
                                logEditBox.Enabled = true;
                            }
                        });
                    }
                    catch (Exception) { }   // ダイアログが先に閉じられた場合など。握りつぶしてよい
                });
            };

            dlg.Controls.Add(stage1);
            dlg.Controls.Add(stage2);
            dlg.Controls.Add(stage3);
            dlg.Controls.Add(copyLogBtn);
            dlg.Controls.Add(closeBtn);
            dlg.AcceptButton = closeBtn;

            // dev#42b: 未送信→第1段(既定表示のまま) / 送信済み・ログ不変→第3段 /
            // 送信済み・ログ変化→第2段を直接表示(再送が既定)
            // 比較は NormalizeLogForComparison() を両辺に通してから行う(date:行など、
            // 内容の変化を伴わない揮発行を比較から除外するため。同メソッドのコメント参照)
            if (!string.IsNullOrEmpty(reportViewUrl))
            {
                string currentLog = BuildDiagnosticsText();
                bool logChanged = lastSentBaseLog == null ||
                    NormalizeLogForComparison(currentLog) != NormalizeLogForComparison(lastSentBaseLog);
                if (logChanged)
                    showConfirmStage(true, true);
                else
                    showSentStage(reportId, reportViewUrl);
            }

            using (dlg) { dlg.ShowDialog(this); }
        }

        // クリップボードへ渡す文字列からユーザーを特定できる情報を伏せる。
        // 呼び出し元はコピー直前のみで使うこと(画面表示・ログファイルには適用しない)。
        // dev#7(2026-07-30): 三段構成(work\issue_zero\i7\NOTES.md)の最終防衛段。
        // convert.ps1/export_from_unity.ps1側のfactify(Mask-Path引退+各所factify)を
        // すり抜けた場合や、まだ手当てされていない出力元(将来判明する事故パターン含む)の
        // 保険として、既知フォルダ限定でなく任意ドライブの絶対パス/UNCパスを一般に
        // 検出する汎用ガード(手順5)を追加した。単体表はCheckSanitizeForClipboardLogic
        // (--check-sanitize-clipboard で検査可能、tests\shipcheck\test_sanitize_clipboard_cs.py)。
        // internal static(NormalizeDistChannel等と同じくI/O・インスタンス状態に依存しない
        // 純粋関数)にして、隠しCLIから直接呼べるようにしてある。
        internal static string SanitizeForClipboard(string text)
        {
            if (string.IsNullOrEmpty(text)) return text;

            // 1) 既知フォルダのパスを伏せる。%LOCALAPPDATA% / %APPDATA% は %USERPROFILE% の
            //    サブフォルダなので、%USERPROFILE% を先に置換すると
            //    「%USERPROFILE%\AppData\Local」のような中途半端な結果になり伏字の意味が薄れる。
            //    そのため実際のパス文字列が長いものから順に置換する(決め打ちせず環境変数から取得)。
            List<string[]> folderMap = new List<string[]>();
            AddFolderToken(folderMap, Environment.SpecialFolder.LocalApplicationData, "%LOCALAPPDATA%");
            AddFolderToken(folderMap, Environment.SpecialFolder.ApplicationData, "%APPDATA%");
            AddFolderToken(folderMap, Environment.SpecialFolder.UserProfile, "%USERPROFILE%");

            // 長い順に並べ替え(要素数が数個なので単純な選択ソートで十分)
            for (int i = 0; i < folderMap.Count; i++)
            {
                for (int j = i + 1; j < folderMap.Count; j++)
                {
                    if (folderMap[j][0].Length > folderMap[i][0].Length)
                    {
                        string[] tmp = folderMap[i];
                        folderMap[i] = folderMap[j];
                        folderMap[j] = tmp;
                    }
                }
            }

            foreach (string[] kv in folderMap)
            {
                text = Regex.Replace(text, Regex.Escape(kv[0]), kv[1], RegexOptions.IgnoreCase);
            }

            // 2) SteamID64(7656119で始まる17桁の数字)
            text = Regex.Replace(text, @"\b7656119\d{10}\b", "<SteamID>");

            // 3) アカウント名がパス以外(プロセス名や作業フォルダ名の一部等)に露出している
            //    場合の保険。3文字以下の短い名前は他の単語を巻き込んで誤爆する恐れがあるため
            //    置換しない(例: アカウント名が "a" や "abc" のケース)
            string userName = Environment.UserName;
            if (!string.IsNullOrEmpty(userName) && userName.Length > 3)
            {
                text = Regex.Replace(text, "(?<![A-Za-z0-9_])" + Regex.Escape(userName) + "(?![A-Za-z0-9_])",
                    "<user>", RegexOptions.IgnoreCase);
            }

            // 4) PCのマシン名も同様の理由で保険として伏せる(短い名前は除外)
            string machineName = Environment.MachineName;
            if (!string.IsNullOrEmpty(machineName) && machineName.Length > 3)
            {
                text = Regex.Replace(text, "(?<![A-Za-z0-9_])" + Regex.Escape(machineName) + "(?![A-Za-z0-9_])",
                    "<machine>", RegexOptions.IgnoreCase);
            }

            // 5) dev#7: 汎用の最終防衛。上記1)は既知の特殊フォルダとの完全一致プレフィックス
            //    しか扱えず、%USERPROFILE%外の別ドライブ・任意フォルダ名(実ユーザー報告
            //    4AL4M4GTで実証: 非%USERPROFILE%ドライブのUnity/VCC・インストール先・
            //    Steamライブラリの絶対パス)は素通りしていた(監査 work\rd_23_audit\AUDIT.md
            //    指摘2)。ここで任意ドライブの絶対パス(X:\...)・UNCパス(\\server\share\...)を
            //    構造保存型(長さ・拡張子のみ)で伏せる。1)〜4)より後に実行することで、
            //    既に%USERPROFILE%等のトークンへ置換済みの文字列(先頭がドライブ文字や
            //    バックスラッシュではない)を誤って再度巻き込まない。
            text = GenericAbsolutePathRegex.Replace(text, m => FactifyGenericPath(m.Value));

            return text;
        }

        // 任意ドライブの絶対パス(例: D:\Users\...\avatar.prefab)またはUNCパス
        // (\\server\share\...)にマッチする。パス文字(空白は単語区切りとして1個までは許容し、
        // その後に空白またはカッコが続く場合はそこで打ち切る)を貪欲に消費する。
        // 例: "C:\Program Files\Unity\Unity.exe" は1つのパスとしてマッチするが、
        // "D:\foo\bar.log (see above)" は "D:\foo\bar.log" までで止まる
        // (直後の空白+"("の手前で打ち切り、後続の診断文まで巻き込まない)。
        // 過剰マッチ(非パス文字列を誤って消費する)は安全側なので許容し、
        // 過少マッチ(パスの一部が生で残る)だけを避ける設計。
        static readonly Regex GenericAbsolutePathRegex = new Regex(
            @"(?:[A-Za-z]:\\|\\\\)[^\s""'<>|?*\r\n]+(?:[ \t](?![ \t(),])[^\s""'<>|?*\r\n]+)*",
            RegexOptions.Compiled);

        // 生パスの代わりに、診断に要る「事実」だけを返す(convert.ps1のGet-PathFacts/
        // pipeline\py\path_privacy.pyと同じ「構造保存型の伏字化」の考え方)。
        // 拡張子は原因切り分けに有用(.pak/.prefab/.log等)かつ個人情報を含まないため残す。
        internal static string FactifyGenericPath(string rawPath)
        {
            if (string.IsNullOrEmpty(rawPath)) return rawPath;
            string ext = "";
            try { ext = Path.GetExtension(rawPath); } catch (Exception) { }
            // 異常に長い/記号だらけの「拡張子」はGetExtensionの誤爆(区切りの無い長い文字列
            // 等)の可能性があるため出さない
            if (ext == null || ext.Length == 0 || ext.Length > 10) ext = "";
            bool isUnc = rawPath.StartsWith(@"\\", StringComparison.Ordinal);
            return string.Format("<path len={0}{1}{2}>", rawPath.Length,
                isUnc ? " unc=true" : "",
                string.IsNullOrEmpty(ext) ? "" : " ext=" + ext);
        }

        static void AddFolderToken(List<string[]> map, Environment.SpecialFolder folder, string token)
        {
            string path = Environment.GetFolderPath(folder);
            // ルート直下等の異常に短い値は誤爆の恐れがあるため対象外にする
            if (!string.IsNullOrEmpty(path) && path.Length > 3)
            {
                map.Add(new string[] { path, token });
            }
        }

        void RemoveApplied()
        {
            if (IsGameRunning())
            {
                MessageBox.Show(T("MsgGameRunningRemove"));
                return;
            }
            string paks = PaksDir();
            if (paks == null) return;
            string target = Path.Combine(paks, InstallName);
            var legacyTargets = new List<string>();
            foreach (string legacyName in LegacyInstallNames)
            {
                string legacy = Path.Combine(paks, legacyName);
                if (File.Exists(legacy)) legacyTargets.Add(legacy);
            }
            if (!File.Exists(target) && legacyTargets.Count == 0)
            {
                statusLabel.Text = T("StatusNoModApplied");
                UpdateAppliedStatus();
                return;
            }
            try
            {
                if (File.Exists(target)) File.Delete(target);
                foreach (string legacy in legacyTargets) File.Delete(legacy);
            }
            catch (Exception ex)
            {
                ShowApplyFailure(T("LabelRemove"), target, ex);
                return;
            }
            UpdateAppliedStatus();
            statusLabel.Text = T("StatusModRemoved");
        }

        // ---------------- WP11(2026-07-27): ヘッドレス配線契約検査 ----------------
        // 「フル変換」クリックが実際に行う job.json生成 → convert.ps1起動 の配線
        // (2026-07-26のcp932事故はGUI経由の出力リダイレクトが引き金だった)を、
        // Unityクリック自動化なしで検査できるようにする隠しCLIモード。
        //
        // 使い方: Uchinoko.exe --emit-wiring <出力先dir> <appRootに使うリポジトリ直下>
        //
        // 実際にGUIが「フル変換」を押した時に呼ぶのと同じメソッド(WriteJob /
        // BuildConvertScriptPath / BuildConvertArgs / FindPwsh)をそのまま呼び出し、
        // その結果(job.jsonの中身、起動しようとするシェル・スクリプトパス・引数)を
        // ファイルへ書き出して終了する。convert.ps1は起動しない。GUIの見た目・
        // 通常起動時の動作(この分岐以外)には一切手を入れていない。
        //
        // 第2引数(repoRoot)について: 検査用にビルドしたexeは配布物と違う場所
        // (例: work\relgate\wp11\...\build\)に置かれるため、通常起動時のappRoot
        // 自動検出(コンストラクタの「exeの隣、無ければ親にpipeline\があるか」判定)
        // だけでは正しいリポジトリ直下を見つけられないことがある。配線検査が見たいのは
        // job.jsonの値そのもの(検体依存、この検査の対象外)ではなく「convert.ps1の
        // 実ファイルを正しいパスで指せているか」なので、appRoot/workRootをこの引数で
        // 明示上書きできるようにしている。WriteJob()等のロジック自体には一切手を
        // 入れていない。
        static void EmitWiring(string outDir, string repoRoot)
        {
            Directory.CreateDirectory(outDir);
            var form = new MainForm();
            form.appRoot = repoRoot;
            form.workRoot = Path.Combine(outDir, "work");
            form.vrmBox.Text = Path.Combine(outDir, "sample_avatar.vrm");

            string jobJson = form.WriteJob();
            string script = form.BuildConvertScriptPath();
            string args = form.BuildConvertArgs(script, jobJson, false, false);
            string shell = form.FindPwsh();

            string jobText;
            try { jobText = File.ReadAllText(jobJson, Encoding.UTF8); }
            catch (Exception ex) { jobText = "<job.json読み込み失敗: " + ex.Message + ">"; }

            var sb = new StringBuilder();
            sb.Append("{\n");
            sb.AppendFormat("  \"job_json_path\": \"{0}\",\n", WiringJsonEscape(jobJson));
            sb.AppendFormat("  \"shell\": \"{0}\",\n", WiringJsonEscape(shell));
            sb.AppendFormat("  \"script\": \"{0}\",\n", WiringJsonEscape(script));
            sb.AppendFormat("  \"args\": \"{0}\"\n", WiringJsonEscape(args));
            sb.Append("}\n");
            File.WriteAllText(Path.Combine(outDir, "wiring.json"), sb.ToString(), new UTF8Encoding(false));
            File.WriteAllText(Path.Combine(outDir, "job.json"), jobText, new UTF8Encoding(false));

            Console.WriteLine("EMIT_WIRING_OK");
        }

        static string WiringJsonEscape(string s)
        {
            if (s == null) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }

        // ---------------- dev#25: 報告送信の配線検査(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --send-report <出力先dir>
        //
        // 「問合せ」ボタン(第2段のOK)が最終的に呼ぶのと同一のコアメソッド
        // (BuildReportPayloadJson / SendReportPayload)をそのまま呼び、
        // ここでは従来どおり無編集本文(BuildDiagnosticsText()そのまま)で送る
        // 引数無しオーバーロードを使う(dev#42でGUI用に編集済み本文を渡せる
        // オーバーロードを追加したが、CLIはこの挙動を変えない)。
        //   payload.json    — 実際に送るJSONペイロード(伏字化確認のダンプ用)
        //   masked_log.txt  — gzip前の伏字化済みログ本文
        //   send_result.txt — ok/id/view_url/error
        // を書き出して終了する。伏字化の負の対照が取れるように、セッションログへ
        // 実ユーザー名・実プロファイルパスを含むダミー行を意図的に注入してから
        // ペイロードを作る(=payload.jsonに生のユーザー名が残っていたら伏字化の
        // 配線が切れている、と機械判定できる)。
        // 接続先は環境変数 D2P_REPORT_BASEURL で差し替え可能(オフライン縮退の試験用)
        static void SendReportCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            var form = new MainForm();
            form.sessionLog.AppendLine("[selftest] raw user name: " + Environment.UserName);
            form.sessionLog.AppendLine("[selftest] raw profile path: " +
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                    "Documents\\avatar_test.vrm"));
            string maskedLog;
            string payload = form.BuildReportPayloadJson(out maskedLog);
            File.WriteAllText(Path.Combine(outDir, "payload.json"), payload, new UTF8Encoding(false));
            File.WriteAllText(Path.Combine(outDir, "masked_log.txt"), maskedLog, new UTF8Encoding(false));
            ReportSendResult res = SendReportPayload(payload, null); // CLIは常に新規POST(挙動不変)
            var sb = new StringBuilder();
            sb.AppendLine("ok=" + (res.Ok ? "1" : "0"));
            sb.AppendLine("id=" + (res.Id ?? ""));
            sb.AppendLine("view_url=" + (res.ViewUrl ?? ""));
            sb.AppendLine("error=" + (res.Error ?? ""));
            File.WriteAllText(Path.Combine(outDir, "send_result.txt"), sb.ToString(), new UTF8Encoding(false));
        }

        // ---------------- dev#29: 辞書完全性 + 言語判定の機械検査(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --check-i18n <出力先dir>
        //
        // 1) Strings.Table の全キーが5言語(ja/en/ko/zh-TW/zh-CN)とも非空文字列を
        //    持つことを検査する(受入条件2: 辞書の完全性)。
        // 2) DetectLangFromCulture()の単体表(ja/ko/zh-TW/zh-CN/en/その他/不正の7ケース、
        //    受入条件5)を実行し、期待値と突き合わせる。
        // どちらも純粋な検査(ファイル書き込み・ネットワーク等の副作用なし)。
        // 結果は i18n_check.txt へ書き出し、両方PASSならI18N_CHECK_OK/exit 0、
        // どちらか1つでもFAILならI18N_CHECK_FAIL/exit 1を返す。

        /// <summary>Strings.Table の全キーが5要素とも非空かを検査する純関数。
        /// problemsに違反箇所(キー名+詳細)を積む。戻り値は「問題ゼロ」かどうか。</summary>
        internal static bool CheckDictionaryCompleteness(out List<string> problems)
        {
            problems = new List<string>();
            foreach (KeyValuePair<string, string[]> kv in Strings.Table)
            {
                if (kv.Value == null || kv.Value.Length != 5)
                {
                    problems.Add(kv.Key + ": expected 5 language entries, got " +
                        (kv.Value == null ? "null" : kv.Value.Length.ToString()));
                    continue;
                }
                for (int i = 0; i < kv.Value.Length; i++)
                {
                    if (string.IsNullOrEmpty(kv.Value[i]))
                        problems.Add(kv.Key + ": empty at index " + i + " (" + ((Lang)i) + ")");
                }
            }
            return problems.Count == 0;
        }

        static void CheckI18nCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            var sb = new StringBuilder();

            List<string> problems;
            bool dictOk = CheckDictionaryCompleteness(out problems);
            sb.AppendLine("=== dictionary completeness ===");
            sb.AppendLine("total_keys=" + Strings.Table.Count);
            sb.AppendLine("result=" + (dictOk ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            sb.AppendLine();

            sb.AppendLine("=== DetectLangFromCulture unit table (7 cases) ===");
            // ja / ko / zh-TW / zh-CN / en / その他 / 不正(null) の7ケース(受入条件5)
            string[] inputs = { "ja-JP", "ko-KR", "zh-TW", "zh-CN", "en-US", "fr-FR", null };
            Lang[] expected = { Lang.Ja, Lang.Ko, Lang.ZhTW, Lang.ZhCN, Lang.En, Lang.En, Lang.En };
            string[] caseLabel = { "ja", "ko", "zh-TW", "zh-CN", "en", "other(fr-FR)", "invalid(null)" };
            bool langOk = true;
            for (int i = 0; i < inputs.Length; i++)
            {
                Lang actual = DetectLangFromCulture(inputs[i]);
                bool ok = actual == expected[i];
                if (!ok) langOk = false;
                sb.AppendLine(string.Format("  case={0,-14} input={1,-8} expected={2,-6} actual={3,-6} {4}",
                    caseLabel[i], inputs[i] ?? "<null>", expected[i], actual, ok ? "OK" : "FAIL"));
            }
            sb.AppendLine();

            sb.AppendLine("=== S(key, lang) explicit-language lookup unit table (dev#150系実機テスト由来、dev#218で対象キー入替) ===");
            // dev#150系実機テストの動機だった確認MessageBox(MsgLanguageSaved/
            // TitleLanguageSetting)はdev#218で廃止し、辞書からも削除済み(完全に
            // 死んだキーを検査対象に残さない)。ただしS(key, lang)自体(Strings.Current
            // に依存せず引数のlangだけで文字列を返す)は他の生きた用途(langCombo選択時の
            // ApplyLanguage、CheckApplyLanguageLogicのTipLanguageSwitch検査等)で
            // 引き続き使われているため、その回帰検査として現役キー2つで代替する。
            Lang savedCurrent = Strings.Current;
            bool langSwitchOk = true;
            try
            {
                string[] checkKeys = { "LabelLanguage", "TipLanguageSwitch" };
                Lang[] allLangs = { Lang.Ja, Lang.En, Lang.Ko, Lang.ZhTW, Lang.ZhCN };
                foreach (string key in checkKeys)
                {
                    string[] table = Strings.Table[key];
                    // Currentをテスト対象と無関係な値に固定し、S(key, lang)がCurrentを
                    // 見ていない(=引数のlangだけで決まる)ことを積極的に確認する。
                    Strings.Current = Lang.Ja;
                    foreach (Lang lang in allLangs)
                    {
                        string expectedText = table[(int)lang];
                        string actual = Strings.S(key, lang);
                        bool ok = actual == expectedText;
                        if (!ok) langSwitchOk = false;
                        sb.AppendLine(string.Format("  key={0,-20} lang={1,-6} expected_matches_actual={2}",
                            key, lang, ok ? "OK" : "FAIL(expected=" + expectedText + " actual=" + actual + ")"));
                    }
                    // 負の対照: Current(Ja固定のまま)とEn選択時の結果が実際に異なることを
                    // 確認する(=もしS(key,lang)が内部でCurrentへフォールバックしていたら
                    // ここで一致してしまい検出できる)。ただし2026-07-30裁定でLabelLanguageは
                    // 全言語で"Language"に統一されたため、この特定キーはJa/Enの辞書値自体が
                    // 一致しており、この負の対照では原理的にCurrent依存バグを検出できない
                    // (一致=バグ、を意味しない)。辞書値が実際に異なるキーに限って対照を実施する
                    // (TipLanguageSwitchは引き続き言語ごとに異なる文言なので有効)。
                    if (table[(int)Lang.Ja] == table[(int)Lang.En])
                    {
                        sb.AppendLine(string.Format(
                            "  negative control: key={0,-20} skipped(Ja/En辞書値が意図的に同一のため対照不能)",
                            key));
                    }
                    else
                    {
                        string viaCurrent = Strings.S(key);
                        string viaEn = Strings.S(key, Lang.En);
                        bool differs = viaCurrent != viaEn;
                        if (!differs) langSwitchOk = false;
                        sb.AppendLine(string.Format("  negative control: key={0,-20} S(key)!=S(key,En) -> {1}",
                            key, differs ? "OK(異なる=Currentに依存していない)" : "FAIL(一致=Current依存のバグが残っている)"));
                    }
                }
            }
            finally
            {
                Strings.Current = savedCurrent;
            }
            sb.AppendLine();

            bool overallOk = dictOk && langOk && langSwitchOk;
            sb.AppendLine("=== overall ===");
            sb.AppendLine(overallOk ? "I18N_CHECK_OK" : "I18N_CHECK_FAIL");

            File.WriteAllText(Path.Combine(outDir, "i18n_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(overallOk ? "I18N_CHECK_OK" : "I18N_CHECK_FAIL");
            Environment.Exit(overallOk ? 0 : 1);
        }

        // ---------------- dev#236: Blenderセットアップ判定の単体表(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --check-blender-setup-decision <出力先dir>
        //
        // 背景: dev#236でモーダル(BlenderSetupDialog)を撤去し、EnsureBlenderReadyOnStartup()
        // をバックグラウンド化した際、実際に何をすべきか(即readyか/フル取得が必要か/
        // 開発環境で手詰まりか)を決める分岐をDecideBlenderSetupAction()という純関数へ
        // 切り出した(ファイルI/O・プロセス起動を一切含まない、bool3個->enum1個)。
        // ここではその全8通りの入力組み合わせを総当たりし、期待値と突き合わせる
        // (--check-i18nと同じ動機・同じ手口。tests\shipcheck\test_blender_setup_decision_cs.py
        // からsubprocessで呼ばれる)。
        //
        // 期待値の根拠:
        //   - ensurePs1が無い(開発チェックアウト等)場合、checkOnlyValidの値に関わらず
        //     exeの有無だけで決まる(旧実装からの踏襲。マーカー検証はensurePs1側の
        //     責務なので、そのスクリプト自体が無ければ検証しようがない)
        //   - ensurePs1がある場合、exeがあってcheckOnlyValid(=Test-D2PMarkerValid相当)が
        //     trueの時だけReadyNoAction。それ以外(exe無し、またはマーカー無効)は
        //     NeedFullSetup(dev#230対策: 「exeがあるだけ」でreadyにしない、が核心)
        internal static bool CheckBlenderSetupDecisionLogic(out List<string> problems)
        {
            problems = new List<string>();
            // (ensurePs1Exists, blenderExeExists, checkOnlyValid, expected)
            var cases = new[]
            {
                Tuple.Create(false, false, false, BlenderSetupAction.DevNotFoundNoScript),
                Tuple.Create(false, false, true,  BlenderSetupAction.DevNotFoundNoScript),
                Tuple.Create(false, true,  false, BlenderSetupAction.ReadyNoAction),
                Tuple.Create(false, true,  true,  BlenderSetupAction.ReadyNoAction),
                Tuple.Create(true,  false, false, BlenderSetupAction.NeedFullSetup),
                Tuple.Create(true,  false, true,  BlenderSetupAction.NeedFullSetup),
                // dev#230の核心: exeはあるがマーカー無効 -> 即readyにせず必ずフル実行
                Tuple.Create(true,  true,  false, BlenderSetupAction.NeedFullSetup),
                Tuple.Create(true,  true,  true,  BlenderSetupAction.ReadyNoAction),
            };
            foreach (var c in cases)
            {
                BlenderSetupAction actual =
                    DecideBlenderSetupAction(c.Item1, c.Item2, c.Item3);
                if (actual != c.Item4)
                {
                    problems.Add(string.Format(
                        "ensurePs1Exists={0} blenderExeExists={1} checkOnlyValid={2}: expected={3} actual={4}",
                        c.Item1, c.Item2, c.Item3, c.Item4, actual));
                }
            }
            return problems.Count == 0;
        }

        static void CheckBlenderSetupDecisionCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckBlenderSetupDecisionLogic(out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== DecideBlenderSetupAction unit table (dev#236, 8 cases) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "blender_setup_decision_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "BLENDER_SETUP_DECISION_CHECK_OK" : "BLENDER_SETUP_DECISION_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // ---------------- dev#288 WP-UXIMPL(2026-07-30): 進捗中間マーカー+早期プレビュー
        // 反映(提案2・3)の単体試験+負の対照(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --check-progress-relay <出力先dir>
        //
        // 背景: 提案2(Phase1完了=39%到達時にLoadPreviews(jobDir)を1回だけ呼ぶ)と
        // 提案3(96%ラベルを「preflight完了済みの事後表示」だと分かる文言へ変更)は
        // どちらもAppendLog()内の##PROGRESS##処理(2026-07-30改修)に閉じている。
        // 実プロセス・実Blender・GUI表示を一切使わず、AppendLog()へ直接
        // ##PROGRESS##行を渡して機械検査する(既存の--check-blender-setup-decision等と
        // 同じ動機。かつてここにあった--check-warm-startupはSignPath審査対応
        // (2026-07-31)でdevtools\shipcheck_src\へ分離済み)。
        //   1) 正: pct=39到達でLoadPreviews()が実際に呼ばれ、previewFront/Side.Image
        //      が非nullになること(=「実装した」だけでなく「効いている」ことの確認)。
        //   2) 正(1回だけ): pct=39到達後、別のpct(58)がもう一度来てもLoadPreviews()を
        //      再度呼ばない(previewFront.Imageの参照が変わらないことで確認。同じ内容の
        //      画像でもLoadPreviews()は毎回新しいImageインスタンスを作るため、再呼び出しが
        //      あれば参照は必ず変わる)。
        //   3) 負の対照①(境界): pct=38(39未満)ではLoadPreviews()を呼ばないこと。
        //      これが無いと「常にプレビューを読み込むだけの無条件コード」でも
        //      ケース1だけは偶然PASSしてしまう(検査の空洞化を防ぐ)。
        //   4) 負の対照②(既存ガードの回帰確認): runningProc==nullなら##PROGRESS##
        //      ブロック自体が丸ごとスキップされる既存仕様(2026-07-26以前からの実装)が、
        //      今回の改修後も壊れていないこと(busyBar/statusLabel/previewのいずれも
        //      変化しないこと)。
        //   5) 提案3: pct=96 + 新ラベル("Packaging complete, verifying result")を
        //      渡すと、statusLabel.Textが期待どおり整形されること。
        internal static bool RunProgressRelayChecks(string outDir, out List<string> problems)
        {
            problems = new List<string>();
            Directory.CreateDirectory(outDir);
            var form = new MainForm();
            form.runningProc = new Process();   // Start()はしない。非null判定だけが対象

            // ---- 準備: プレビュー画像2枚(前面・側面)を用意 ----
            string jobDir = Path.Combine(outDir, "job1");
            string convertedDir = Path.Combine(jobDir, "converted");
            Directory.CreateDirectory(convertedDir);
            string frontPath = Path.Combine(convertedDir, "preview_male_stand.png");
            string sidePath = Path.Combine(convertedDir, "preview_male_stand_side.png");
            using (var bmp = new Bitmap(2, 2))
            {
                bmp.Save(frontPath, System.Drawing.Imaging.ImageFormat.Png);
                bmp.Save(sidePath, System.Drawing.Imaging.ImageFormat.Png);
            }

            // ---- case3(負の対照①、先にやる): pct=38(39未満)ではまだ読み込まれない ----
            form.currentPipelineJobDir = jobDir;
            form.earlyPreviewLoadedThisRun = false;
            form.AppendLog("##PROGRESS## 38 Retargeting skeleton + preview (parallel: Male, Female)");
            if (form.previewFront.Image != null || form.previewSide.Image != null)
                problems.Add("case3(負の対照①): pct=38(39未満)なのにLoadPreviews()が呼ばれてしまった"
                    + "(常時読み込みの無条件実装との区別ができていない疑い)");
            if (form.earlyPreviewLoadedThisRun)
                problems.Add("case3: pct=38でearlyPreviewLoadedThisRunがtrueになった(境界条件が39でない疑い)");

            // ---- case1(正): pct=39到達でLoadPreviews()が実際に効く ----
            form.AppendLog("##PROGRESS## 39 Skeleton + preview complete (parallel)");
            if (form.previewFront.Image == null)
                problems.Add("case1: pct=39到達後もpreviewFront.Imageがnullのまま(LoadPreviews()が効いていない)");
            if (form.previewSide.Image == null)
                problems.Add("case1: pct=39到達後もpreviewSide.Imageがnullのまま(LoadPreviews()が効いていない)");
            if (!form.earlyPreviewLoadedThisRun)
                problems.Add("case1: pct=39到達後もearlyPreviewLoadedThisRunがfalseのまま");
            if (form.busyBar.Value != 39)
                problems.Add("case1: busyBar.Valueが39になっていない(実測=" + form.busyBar.Value + ")");

            // ---- case2(正、1回だけ): 別のpct(58)が来てもLoadPreviews()を再度呼ばない ----
            object frontRefBefore = form.previewFront.Image;
            object sideRefBefore = form.previewSide.Image;
            form.AppendLog("##PROGRESS## 58 Preparing template assets");
            if (!ReferenceEquals(form.previewFront.Image, frontRefBefore)
                || !ReferenceEquals(form.previewSide.Image, sideRefBefore))
                problems.Add("case2: pct=58(2回目の39%以上到達)でLoadPreviews()が再度呼ばれた"
                    + "(Imageの参照が変わった=「1回だけ」の制約が効いていない)");

            // ---- case4(負の対照②、既存ガードの回帰確認): runningProc==nullなら丸ごとskip ----
            var form2 = new MainForm();
            form2.runningProc = null;
            form2.currentPipelineJobDir = jobDir;
            form2.earlyPreviewLoadedThisRun = false;
            int barBefore = form2.busyBar.Value;
            form2.AppendLog("##PROGRESS## 39 Skeleton + preview complete (parallel)");
            if (form2.busyBar.Value != barBefore)
                problems.Add("case4(負の対照②): runningProc==nullなのにbusyBar.Valueが変化した"
                    + "(既存の実行中ガードが壊れている)");
            if (form2.previewFront.Image != null)
                problems.Add("case4(負の対照②): runningProc==nullなのにLoadPreviews()が呼ばれてしまった");
            if (form2.earlyPreviewLoadedThisRun)
                problems.Add("case4(負の対照②): runningProc==nullなのにearlyPreviewLoadedThisRunがtrueになった");

            // ---- case5(提案3): 96%の新ラベルがstatusLabelへ正しく整形されること ----
            var form3 = new MainForm();
            // dev#304裁定Aで進捗ラベルが翻訳対象になったため、statusLabel.Textは
            // Strings.Currentに依存するようになった(MainForm()コンストラクタが
            // 実行環境のCultureInfoから初期値を決めるため、開発機のOS言語設定に
            // よってこの単体表の期待値が揺れてしまう)。この単体表は「整形ロジック
            // 自体」の検査なので、言語をEnへ明示的に固定して決定的にする
            // (English側のProgressLabelsエントリは原文と同一の文字列にしてあるため、
            // 期待値の文字列自体はdev#304適用前と変わらない)。
            Strings.Current = Lang.En;
            form3.runningProc = new Process();
            form3.AppendLog("##PROGRESS## 96 Packaging complete, verifying result");
            string expectedStatus96 = "Packaging complete, verifying result... (96%)";
            if (form3.statusLabel.Text != expectedStatus96)
                problems.Add("case5: 96%のstatusLabel.Textが期待と異なる: 実測="
                    + form3.statusLabel.Text + " 期待=" + expectedStatus96);
            if (form3.busyBar.Value != 96)
                problems.Add("case5: busyBar.Valueが96になっていない(実測=" + form3.busyBar.Value + ")");

            return problems.Count == 0;
        }

        static void CheckProgressRelayCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = RunProgressRelayChecks(outDir, out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== progress relay + early preview reload wiring check (dev#288 WP-UXIMPL) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "progress_relay_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "PROGRESS_RELAY_CHECK_OK" : "PROGRESS_RELAY_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // ---------------- dev#304裁定A(2026-07-30): 進捗ラベル辞書化の単体試験+
        // 負の対照(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --check-progress-label-i18n <出力先dir>
        //
        // --check-progress-relay(PR#307)と同じ動機・同じ手口を踏襲した拡張(WP-LABELI18N
        // 安全制約「先例に倣い拡張してよい」)。画面・実プロセス・ネットワークI/Oを
        // 一切使わず、Strings.TranslateProgressLabel()系の純関数とAppendLog()経由の
        // 統合経路を機械検査する:
        //   1) 辞書完全性: ProgressLabels/ProgressLabelTemplatesの全エントリが
        //      5言語とも非空であること(Strings.Tableに対する既存CheckDictionaryCompleteness
        //      と同じ検査をこの辞書にも適用する)。
        //   2) 正: 既知ラベルが実際に5言語それぞれで翻訳されること(en以外は原文と
        //      異なること、enは原文と同一であること=既存試験の期待文字列を変えない
        //      設計上の要請)。
        //   3) 正(動的テンプレート): 性別名などの可変部を含むラベルが、可変部は
        //      そのまま・静的部分だけ翻訳されること。
        //   4) 負の対照①(未知ラベル): 辞書に無いラベルは原文のままフォールバックする
        //      こと(無表示・"??"マーカーにならないこと)。
        //   5) 負の対照②(辞書エントリを意図的に破壊): TranslateProgressLabelFrom()へ
        //      テスト専用の壊れた辞書(全言語空文字列のエントリ、5要素に満たない配列)
        //      を注入し、例外を投げず・空文字列にもならず、原文へフォールバックする
        //      ことを確認する(検査自体がフォールバックの機能を検出できることの証明)。
        //   6) 統合(「実装した」と「効いている」の区別): AppendLog()経由でstatusLabel.Text
        //      が既知ラベルは翻訳され、未知ラベルは原文のまま出ることを確認する
        //      (純関数のテストだけでなく実際の配線を確認する)。
        internal static bool RunProgressLabelI18nChecks(out List<string> problems)
        {
            problems = new List<string>();

            // ---- case1: ProgressLabels/ProgressLabelTemplatesの辞書完全性 ----
            foreach (KeyValuePair<string, string[]> kv in Strings.ProgressLabels)
            {
                if (kv.Value == null || kv.Value.Length != 5)
                {
                    problems.Add("case1(完全性): " + kv.Key + ": 5言語ぶんの配列が無い(実測="
                        + (kv.Value == null ? "null" : kv.Value.Length.ToString()) + ")");
                    continue;
                }
                for (int i = 0; i < kv.Value.Length; i++)
                {
                    if (string.IsNullOrEmpty(kv.Value[i]))
                        problems.Add("case1(完全性): " + kv.Key + ": index " + i + " ("
                            + ((Lang)i) + ") が空");
                }
            }
            foreach (Strings.ProgressLabelTemplate t in Strings.ProgressLabelTemplates)
            {
                if (t.Format == null || t.Format.Length != 5)
                {
                    problems.Add("case1(完全性): テンプレート " + t.Pattern + ": 5言語ぶんの配列が無い");
                    continue;
                }
                for (int i = 0; i < t.Format.Length; i++)
                {
                    if (string.IsNullOrEmpty(t.Format[i]))
                        problems.Add("case1(完全性): テンプレート " + t.Pattern + ": index " + i
                            + " (" + ((Lang)i) + ") が空");
                }
            }

            // ---- case2(正): 既知ラベルが5言語それぞれで翻訳される。enは原文と同一 ----
            const string knownRaw = "Preparing";
            string enTranslated = Strings.TranslateProgressLabel(knownRaw, Lang.En);
            if (enTranslated != knownRaw)
                problems.Add("case2: En訳が原文と異なる(設計上は原文と同一のはず): 実測="
                    + enTranslated);
            Lang[] nonEnglish = { Lang.Ja, Lang.Ko, Lang.ZhTW, Lang.ZhCN };
            foreach (Lang lang in nonEnglish)
            {
                string translated = Strings.TranslateProgressLabel(knownRaw, lang);
                if (translated == knownRaw)
                    problems.Add("case2: " + lang + "訳が原文のまま(翻訳されていない): " + translated);
                if (string.IsNullOrEmpty(translated))
                    problems.Add("case2: " + lang + "訳が空文字列(フォールバックが壊れている)");
            }

            // ---- case3(正、動的テンプレート): 可変部(性別名)はそのまま・静的部分だけ翻訳 ----
            string dynRaw = "Retargeting skeleton (Female)";
            string dynJa = Strings.TranslateProgressLabel(dynRaw, Lang.Ja);
            if (!dynJa.Contains("Female"))
                problems.Add("case3: 動的テンプレートで可変部(Female)が失われた: 実測=" + dynJa);
            if (dynJa == dynRaw)
                problems.Add("case3: 動的テンプレートの静的部分が翻訳されていない(原文のまま): " + dynJa);
            string dynEn = Strings.TranslateProgressLabel(dynRaw, Lang.En);
            if (dynEn != dynRaw)
                problems.Add("case3: 動的テンプレートのEn訳が原文と異なる(設計上は原文と同一のはず): "
                    + dynEn);

            // ---- case4(負の対照①): 辞書に無いラベルは原文のままフォールバック ----
            const string unknownRaw = "This label is intentionally absent from the dictionary";
            foreach (Lang lang in new[] { Lang.Ja, Lang.En, Lang.Ko, Lang.ZhTW, Lang.ZhCN })
            {
                string translated = Strings.TranslateProgressLabel(unknownRaw, lang);
                if (translated != unknownRaw)
                    problems.Add("case4(負の対照①): " + lang + "で未知ラベルが原文と異なる文字列になった"
                        + "(無表示/誤表示の疑い): 実測=" + translated);
            }

            // ---- case5(負の対照②): 辞書エントリを意図的に破壊してもフォールバックが機能する ----
            // 全言語空文字列のエントリ(実運用では起きないはずの壊れ方)。
            var brokenTable = new Dictionary<string, string[]> {
                { "Broken all-empty", new[] { "", "", "", "", "" } },
                { "Broken short array", new[] { "短い配列" } },   // 5要素未満(想定外の壊れ方)
            };
            string brokenResult1 = Strings.TranslateProgressLabelFrom(
                "Broken all-empty", Lang.Ja, brokenTable, Strings.ProgressLabelTemplates);
            if (brokenResult1 != "Broken all-empty")
                problems.Add("case5(負の対照②): 全言語空のエントリで原文フォールバックが機能しなかった: 実測="
                    + brokenResult1);
            // Lang.Ko(index 2)は1要素配列の範囲外 -> index0へのフォールバック分岐を通る
            // (Lang.Jaのindex 0で試すと範囲内アクセスになってしまい、この分岐を検査できない)
            string brokenResult2 = Strings.TranslateProgressLabelFrom(
                "Broken short array", Lang.Ko, brokenTable, Strings.ProgressLabelTemplates);
            if (brokenResult2 != "短い配列")
                problems.Add("case5(負の対照②): 短い配列でindex0へのフォールバックが機能しなかった: 実測="
                    + brokenResult2);
            // さらに壊した場合(index0も空): 例外を投げず原文へ落ちること
            var brokenTable2 = new Dictionary<string, string[]> {
                { "Broken empty index0", new string[0] },
            };
            string brokenResult3 = Strings.TranslateProgressLabelFrom(
                "Broken empty index0", Lang.Ja, brokenTable2, Strings.ProgressLabelTemplates);
            if (brokenResult3 != "Broken empty index0")
                problems.Add("case5(負の対照②): 0要素配列で原文フォールバックが機能しなかった: 実測="
                    + brokenResult3);

            // ---- case6(統合): AppendLog()経由でstatusLabel.Textが実際に翻訳される ----
            Lang savedCurrent = Strings.Current;
            try
            {
                var form = new MainForm();
                form.runningProc = new Process();
                Strings.Current = Lang.Ja;
                form.AppendLog("##PROGRESS## 55 Generating MOD files");
                string expectedJa = Strings.ProgressLabels["Generating MOD files"][(int)Lang.Ja]
                    + "... (55%)";
                if (form.statusLabel.Text != expectedJa)
                    problems.Add("case6(統合、既知ラベル): Ja表示でstatusLabel.Textが期待と異なる: 実測="
                        + form.statusLabel.Text + " 期待=" + expectedJa);

                // ---- case7(統合、負の対照): 未知ラベルはAppendLog経由でも原文のまま出る ----
                var form2 = new MainForm();
                form2.runningProc = new Process();
                Strings.Current = Lang.Ja;
                form2.AppendLog("##PROGRESS## 70 " + unknownRaw);
                string expectedUnknown = unknownRaw + "... (70%)";
                if (form2.statusLabel.Text != expectedUnknown)
                    problems.Add("case7(統合、未知ラベル): Ja表示でも原文フォールバックされるはずが異なる: 実測="
                        + form2.statusLabel.Text + " 期待=" + expectedUnknown);
            }
            finally
            {
                Strings.Current = savedCurrent;
            }

            return problems.Count == 0;
        }

        static void CheckProgressLabelI18nCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = RunProgressLabelI18nChecks(out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== progress label i18n dictionary check (dev#304 裁定A) ===");
            sb.AppendLine("progress_label_count=" + Strings.ProgressLabels.Count);
            sb.AppendLine("progress_label_template_count=" + Strings.ProgressLabelTemplates.Length);
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "progress_label_i18n_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "PROGRESS_LABEL_I18N_CHECK_OK" : "PROGRESS_LABEL_I18N_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // ---------------- dev#87/#89/#91(wp878991): PalworldCompat単体表(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --check-palworld-compat <出力先dir>
        //
        // PalworldCompat(このファイル末尾の独立静的クラス)の判定ロジックを、画面を
        // 出さず・実機のPalworldインストールも使わずに検査する(--check-i18nと同じ動機:
        // C#にはこのリポジトリで使えるNuGet/xUnit系のテストランナーが無いため、
        // ビルド済みexeへ隠しCLIとして仕込み、python側のpytestからsubprocessで
        // 呼び出して合否をアサートする ―― tests\shipcheck\test_palworld_compat_cs.py 参照)。
        //
        // 受入ゲート項目1(判定ロジックの各分岐)との対応:
        //   case1/2 … 既知pakハッシュ(実際にはbuildid+pakサイズの組)一致
        //   case3   … 抽出物マニフェスト一致(dev#91の核心、版番号は未知でもよい)
        //   case7   … リモートリスト(dev#89)のオフラインフォールバック(bundledのみ)
        //   case2   … リモートリストのマージ(既知一覧の拡張)
        //   case4/8 … 負の対照(未知版+抽出物不一致 / 同梱リスト空+オフライン)
        internal static bool CheckPalworldCompatLogic(out List<string> problems)
        {
            problems = new List<string>();
            const string bundledJson = "{\"known_versions\":[{\"build_id\":\"111\",\"pak_size\":1000,"
                + "\"label\":\"1.0.1\"}],\"known_vanilla_manifest_sha256\":[\"aaaa\"]}";

            // case1: 既知版番号(buildid+pakサイズ)に一致 -> 警告しない
            {
                var known = PalworldCompat.MergeKnownGood(bundledJson, null);
                var det = new PalworldDetection { Detected = true, BuildId = "111", PakSize = 1000 };
                var st = PalworldCompat.Evaluate(known, det, null);
                if (!(st.Detected && st.KnownVersion && !st.ShouldWarn))
                    problems.Add("case1(known version): unexpected status ShouldWarn=" + st.ShouldWarn);
            }

            // case2: リモート限定の既知版(dev#89)がマージされ、かつ同梱分も残ること
            {
                const string remote = "{\"known_versions\":[{\"build_id\":\"222\",\"pak_size\":2000,"
                    + "\"label\":\"1.0.2\"}]}";
                var known = PalworldCompat.MergeKnownGood(bundledJson, remote);
                var det = new PalworldDetection { Detected = true, BuildId = "222", PakSize = 2000 };
                var st = PalworldCompat.Evaluate(known, det, null);
                if (!(st.KnownVersion && !st.ShouldWarn))
                    problems.Add("case2(remote-only known version): unexpected status ShouldWarn=" + st.ShouldWarn);
                if (!PalworldCompat.IsKnownVersion(known, "111", 1000))
                    problems.Add("case2: merge dropped the bundled entry (should be additive, not replace)");
            }

            // case3(dev#91の核心): 版番号は未知でも抽出物マニフェストが既知一致なら警告しない
            {
                var known = PalworldCompat.MergeKnownGood(bundledJson, null);
                var det = new PalworldDetection { Detected = true, BuildId = "999", PakSize = 9999 };
                var st = PalworldCompat.Evaluate(known, det, "aaaa");
                if (!(st.ManifestAvailable && st.KnownManifest && !st.ShouldWarn))
                    problems.Add("case3(known manifest, unknown version): unexpected status ShouldWarn=" + st.ShouldWarn);
            }

            // case4(負の対照①): 未知版+抽出物マニフェストも不一致 -> 警告する
            {
                var known = PalworldCompat.MergeKnownGood(bundledJson, null);
                var det = new PalworldDetection { Detected = true, BuildId = "999", PakSize = 9999 };
                var st = PalworldCompat.Evaluate(known, det, "zzzz");
                if (!(st.ShouldWarn && st.ManifestAvailable && !st.KnownManifest))
                    problems.Add("case4(negative control: unknown version+manifest mismatch): "
                        + "should warn but ShouldWarn=" + st.ShouldWarn);
            }

            // case5: マニフェスト未取得(null) -> 警告する側に倒れる(待つかはCheckPalworldVersionOnce側の責務)
            {
                var known = PalworldCompat.MergeKnownGood(bundledJson, null);
                var det = new PalworldDetection { Detected = true, BuildId = "999", PakSize = 9999 };
                var st = PalworldCompat.Evaluate(known, det, null);
                if (!(st.ShouldWarn && !st.ManifestAvailable))
                    problems.Add("case5(manifest not available yet): unexpected status ShouldWarn=" + st.ShouldWarn);
            }

            // case6: 判定不能(Paksフォルダが見つからない) -> 従来どおり黙って動く(警告しない)
            {
                var known = PalworldCompat.MergeKnownGood(bundledJson, null);
                var det = new PalworldDetection { Detected = false };
                var st = PalworldCompat.Evaluate(known, det, null);
                if (!(!st.Detected && !st.ShouldWarn))
                    problems.Add("case6(undetectable): unexpected status Detected=" + st.Detected
                        + " ShouldWarn=" + st.ShouldWarn);
            }

            // case7(dev#89): オフライン(remoteBlockJsonOrNull=null) -> 同梱データのみにフォールバック
            {
                var known = PalworldCompat.MergeKnownGood(bundledJson, null);
                if (known.Versions.Count != 1 || known.ManifestHashes.Count != 1)
                    problems.Add("case7(offline fallback): expected bundled-only 1+1 entries, got "
                        + known.Versions.Count + "+" + known.ManifestHashes.Count);
            }

            // case8(負の対照②): 同梱リストが空(改変/未知化)+オフライン -> 元なら既知の値でも警告する
            {
                var known = PalworldCompat.MergeKnownGood(
                    "{\"known_versions\":[],\"known_vanilla_manifest_sha256\":[]}", null);
                var det = new PalworldDetection { Detected = true, BuildId = "111", PakSize = 1000 };
                var st = PalworldCompat.Evaluate(known, det, null);
                if (!st.ShouldWarn)
                    problems.Add("case8(negative control: bundled list emptied+offline): "
                        + "should warn but ShouldWarn=" + st.ShouldWarn);
            }

            // case9(dev#87): 診断ログ用の1行が検出値・対応リストの両方を数字入りで残すこと
            {
                var known = PalworldCompat.MergeKnownGood(bundledJson, null);
                var det = new PalworldDetection { Detected = false };
                var st = PalworldCompat.Evaluate(known, det, null);
                string line = PalworldCompat.BuildLogLine(known, st);
                if (!line.StartsWith("palworld: not found") || !line.Contains("111"))
                    problems.Add("case9(log line, not found): unexpected content: " + line);

                det = new PalworldDetection { Detected = true, BuildId = "111", PakSize = 1000 };
                st = PalworldCompat.Evaluate(known, det, null);
                line = PalworldCompat.BuildLogLine(known, st);
                if (!line.Contains("111") || !line.Contains("1.0.1"))
                    problems.Add("case9(log line, known version): missing detected/supported numbers: " + line);
            }

            // case10: JsonObj()がネストした配列要素オブジェクトの"}"で早期終了せず、
            // 波括弧の深さを正しく数えてブロック全体を取り出せること
            {
                const string nested = "{\"latest\":\"2.1.0\",\"palworld_known_good\":{\"known_versions\":"
                    + "[{\"build_id\":\"1\",\"pak_size\":1,\"label\":\"a\"},"
                    + "{\"build_id\":\"2\",\"pak_size\":2,\"label\":\"b\"}],"
                    + "\"known_vanilla_manifest_sha256\":[\"h1\",\"h2\"]},\"other\":1}";
                string block = JsonObj(nested, "palworld_known_good");
                var versions = block != null ? PalworldCompat.ParseKnownVersions(block) : new List<KnownPalworldVersion>();
                var hashes = block != null ? PalworldCompat.ParseKnownManifestHashes(block) : new List<string>();
                if (versions.Count != 2 || hashes.Count != 2)
                    problems.Add("case10(JsonObj balanced-brace extraction): expected 2+2, got "
                        + versions.Count + "+" + hashes.Count + " block=" + (block ?? "<null>"));
            }

            return problems.Count == 0;
        }

        // ---------------- dev#98/#103: 他MOD検出(CountOtherPaks/SummarizeOtherPaks)単体表(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --check-other-pak <出力先dir>
        //
        // 実機のPalworldインストール状況に一切依存せず(--outDir配下に自前で作った
        // 使い捨てフォルダのみを使う)、伏字化裁定(dev#103: ファイル名は出さず
        // 拡張子+件数のみ)が実装どおりに効いているかを機械検査する。
        internal static bool CheckOtherPakLogic(string workDir, out List<string> problems)
        {
            problems = new List<string>();
            string fakePaks = Path.Combine(workDir, "fake_paks_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(fakePaks);
            try
            {
                File.WriteAllBytes(Path.Combine(fakePaks, PalWindowsPakName), new byte[] { 0 });
                File.WriteAllBytes(Path.Combine(fakePaks, InstallName), new byte[] { 0 });
                File.WriteAllBytes(Path.Combine(fakePaks, LegacyInstallNames[0]), new byte[] { 0 });

                // case1: 自分自身(現行名+レガシー名)とバニラ本体だけ -> 他MODなし
                int? n1 = CountOtherPaks(fakePaks);
                if (n1 != 0)
                    problems.Add("case1(self+legacy+vanilla only): expected 0, got " + n1);
                string line1 = SummarizeOtherPaks(n1);
                if (line1 != "other_paks: none")
                    problems.Add("case1: unexpected summary line: " + line1);

                // case2(正の対照): ダミーの他.pakを1件追加 -> 件数1、かつファイル名は
                // 一切出ない(dev#103裁定の核心。伏字化が漏れていないかの負の対照)
                const string dummyName = "ZZZ_SomeOtherModWithASecretName_P.pak";
                File.WriteAllBytes(Path.Combine(fakePaks, dummyName), new byte[] { 0 });
                int? n2 = CountOtherPaks(fakePaks);
                if (n2 != 1)
                    problems.Add("case2(1 other mod): expected 1, got " + n2);
                string line2 = SummarizeOtherPaks(n2);
                if (line2 != "other_paks: 1 (.pak)")
                    problems.Add("case2: unexpected summary line: " + line2);
                if (line2.IndexOf("SomeOtherMod", StringComparison.OrdinalIgnoreCase) >= 0)
                    problems.Add("case2(negative control FAILED): file name leaked into summary line "
                        + "(violates dev#103 obfuscation ruling): " + line2);

                // case2b: 2件目を追加 -> 件数だけ2に増える
                File.WriteAllBytes(Path.Combine(fakePaks, "AAA_AnotherMod_P.pak"), new byte[] { 0 });
                int? n2b = CountOtherPaks(fakePaks);
                if (n2b != 2)
                    problems.Add("case2b(2 other mods): expected 2, got " + n2b);

                // case3: 撤去したら元に戻る(negative control: 常態への復帰)
                File.Delete(Path.Combine(fakePaks, dummyName));
                File.Delete(Path.Combine(fakePaks, "AAA_AnotherMod_P.pak"));
                int? n3 = CountOtherPaks(fakePaks);
                if (n3 != 0)
                    problems.Add("case3(removed): expected 0, got " + n3);
                string line3 = SummarizeOtherPaks(n3);
                if (line3 != "other_paks: none")
                    problems.Add("case3: unexpected summary line: " + line3);

                // case4: フォルダ不明(判定不能) -> unknown、件数を決め打ちしない
                int? n4 = CountOtherPaks(Path.Combine(workDir, "does_not_exist_" + Guid.NewGuid().ToString("N")));
                if (n4 != null)
                    problems.Add("case4(unresolvable dir): expected null, got " + n4);
                string line4 = SummarizeOtherPaks(n4);
                if (line4 != "other_paks: unknown (paks dir not found)")
                    problems.Add("case4: unexpected summary line: " + line4);
            }
            finally
            {
                try { Directory.Delete(fakePaks, true); } catch (Exception) { }
            }
            return problems.Count == 0;
        }

        static void CheckOtherPakCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckOtherPakLogic(outDir, out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== other-pak detection unit table (dev#98/#103) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "other_pak_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "OTHER_PAK_CHECK_OK" : "OTHER_PAK_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        static void CheckPalworldCompatCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckPalworldCompatLogic(out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== PalworldCompat logic unit table (dev#87/#89/#91) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "palworld_compat_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "PALWORLD_COMPAT_CHECK_OK" : "PALWORLD_COMPAT_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // ---------------- dev#134: インストール/作業先パスの健全性判定(純粋ロジック) ----------------
        // 使い方: Uchinoko.exe --check-path-health <出力先dir>
        //
        // 2026-07-29ぱん裁定でrd_125第14案(GUI「自己診断」ボタン)は却下、「自動で診断して
        // 警告する」方針へ転換された(MainForm.CheckPathHealthOnStartup参照)。ここは
        // その判定本体(I/Oなしの純粋関数)で、pipeline\cli\convert.ps1のGet-PathFacts
        // (非ASCII/UNC/OneDrive配下/パス長、失敗直後の診断用に既存)と同じ観点をC#側の
        // 事前チェックへ転用したもの。長さの閾値200はWindowsのMAX_PATH(260)から、
        // 変換パイプラインが後段で継ぎ足す典型的なサブパス分の余裕を差し引いた値
        // (実測合わせの調整ではない)。事前チェック用なので、convert.ps1側と違い
        // hasSpaceは持たない(空白は既存コードが全経路で引用符付けしており実害の実績が
        // 無いため、警告扱いにすると誤検知が増えるだけと判断。パス長超過・UNC・OneDrive
        // 配下は個別に実害事例/既知の落とし穴があるものだけを対象にした)。
        const int PathLengthWarnThreshold = 200;

        static PathHealthFacts BuildPathFacts(string label, string path, string oneDriveRootOrNull)
        {
            var f = new PathHealthFacts { Label = label };
            if (string.IsNullOrEmpty(path)) return f;
            f.Length = path.Length;
            foreach (char c in path) { if (c > 127) { f.NonAscii = true; break; } }
            f.Unc = path.StartsWith("\\\\", StringComparison.Ordinal);
            if (!string.IsNullOrEmpty(oneDriveRootOrNull))
                f.UnderOneDrive = path.StartsWith(oneDriveRootOrNull, StringComparison.OrdinalIgnoreCase);
            return f;
        }

        static bool PathHealthHasTooLong(PathHealthFacts f) { return f.Length > PathLengthWarnThreshold; }

        static bool PathHealthProblem(PathHealthFacts f)
        {
            return PathHealthHasTooLong(f) || f.Unc || f.UnderOneDrive;
        }

        static string PathHealthLine(PathHealthFacts f)
        {
            var notes = new List<string>();
            if (PathHealthHasTooLong(f))
                notes.Add("length " + f.Length + " > " + PathLengthWarnThreshold);
            if (f.Unc) notes.Add("UNC path (unsupported)");
            if (f.UnderOneDrive) notes.Add("under OneDrive (sync can lock files during conversion)");
            if (f.NonAscii) notes.Add("non-ASCII characters");
            string status = PathHealthProblem(f) ? "risk" : "ok";
            string detail = notes.Count > 0 ? " [" + string.Join(", ", notes) + "]" : "";
            return f.Label + "_path: " + status + " (len=" + f.Length + ")" + detail;
        }

        internal static bool CheckPathHealthLogic(out List<string> problems)
        {
            problems = new List<string>();

            // case1(基準点): 健全なパス(短い・ASCIIのみ・UNCでない・OneDrive配下でない) -> 問題なし
            {
                var f = BuildPathFacts("install", @"C:\P\Work\DiveToPalworld", null);
                if (PathHealthProblem(f))
                    problems.Add("case1(healthy path): unexpectedly flagged, len=" + f.Length);
                if (f.NonAscii) problems.Add("case1: unexpectedly flagged NonAscii for a pure-ASCII path");
                if (f.Unc) problems.Add("case1: unexpectedly flagged Unc for a plain local path");
                if (f.UnderOneDrive) problems.Add("case1: unexpectedly flagged UnderOneDrive (no OneDrive root given)");
            }

            // case2(負の対照): パスが長すぎる(閾値超え) -> problem、ログ行に長さの数字が残ること
            {
                string longPath = @"C:\" + new string('a', 220);
                var f = BuildPathFacts("install", longPath, null);
                if (!PathHealthProblem(f))
                    problems.Add("case2(long path len=" + longPath.Length + "): expected problem");
                string line = PathHealthLine(f);
                if (line.IndexOf(longPath.Length.ToString(CultureInfo.InvariantCulture), StringComparison.Ordinal) < 0)
                    problems.Add("case2: log line missing the actual length: " + line);
            }

            // case3(境界値): 閾値ちょうど以下の長さは問題にしないこと(過検知の負の対照)
            {
                string atThreshold = @"C:\" + new string('a', PathLengthWarnThreshold - 4);
                var f = BuildPathFacts("boundary", atThreshold, null);
                if (PathHealthProblem(f))
                    problems.Add("case3(boundary length <= threshold): unexpectedly flagged, len=" + f.Length);
            }

            // case4: UNCパスは長さに関わらずproblem(convert.ps1のGet-FreeSpaceGBが
            // 「ドライブレターでない=非対応」とする既存の判定と一致させる)
            {
                var f = BuildPathFacts("unc", @"\\server\share\short", null);
                if (!PathHealthProblem(f))
                    problems.Add("case4(UNC path): expected problem regardless of length");
            }

            // case5(負の対照): OneDrive配下 -> problem。OneDriveルートが渡されない/一致しない
            // 時はUnderOneDriveを立てないこと(誤検知の負の対照も合わせて確認)
            {
                const string oneDrive = @"C:\Users\someone\OneDrive";
                var under = BuildPathFacts("work", oneDrive + @"\DiveToPalworld\work", oneDrive);
                if (!PathHealthProblem(under))
                    problems.Add("case5(under OneDrive): expected problem");
                var outside = BuildPathFacts("work", @"C:\DiveToPalworld\work", oneDrive);
                if (PathHealthProblem(outside))
                    problems.Add("case5(outside OneDrive, root given but not a prefix): unexpectedly flagged");
                var noRoot = BuildPathFacts("work", oneDrive + @"\DiveToPalworld\work", null);
                if (PathHealthProblem(noRoot))
                    problems.Add("case5(OneDrive-like path but root unknown/offline): unexpectedly flagged "
                        + "(OneDrive env var unavailable must fail safe, not false-positive)");
            }

            // case6: 非ASCII文字はnotesに残すが、単独ではproblem扱いにしないこと(過検知の負の対照。
            // 日本語ユーザー名配下は珍しくないため、これだけで警告するとノイズが大きすぎる)
            {
                var f = BuildPathFacts("install", @"C:\Users\ぱん\DiveToPalworld", null);
                if (!f.NonAscii) problems.Add("case6: expected NonAscii=true to be recorded");
                if (PathHealthProblem(f))
                    problems.Add("case6(non-ASCII alone): unexpectedly flagged as problem");
                if (PathHealthLine(f).IndexOf("non-ASCII", StringComparison.Ordinal) < 0)
                    problems.Add("case6: log line should still mention non-ASCII as a note: " + PathHealthLine(f));
            }

            // case7: 空/null パス -> 例外を投げず、長さ0・問題なしとして扱うこと(保険経路)
            {
                var f = BuildPathFacts("install", null, null);
                if (PathHealthProblem(f)) problems.Add("case7(null path): unexpectedly flagged");
                if (f.Length != 0) problems.Add("case7(null path): expected length 0, got " + f.Length);
            }

            return problems.Count == 0;
        }

        static void CheckPathHealthCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckPathHealthLogic(out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== path health logic unit table (dev#134) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "path_health_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "PATH_HEALTH_CHECK_OK" : "PATH_HEALTH_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // ---------------- dev#298: workRootの書き込み可否プローブ+自動フォールバック ----------------
        // 使い方: Uchinoko.exe --check-work-root-fallback <出力先dir>
        //
        // 実報告R7GJY5W3: C:\Program Files\配下にインストールした環境でwork\配下の
        // フォルダ作成がUnauthorizedAccessExceptionで失敗する(export_from_unity.ps1:258の
        // New-Item -ItemType Directory -Force $Out が最初の表面化箇所)。CLAUDE.md
        // 「外部依存パスの原則」(自動発見は必ず手動指定フォールバックを持つ)と同種の
        // 書き込み可否版。ここではUI手動指定ではなく自動フォールバック
        // (%LOCALAPPDATA%\Uchinoko\work)にした——書き込み不可は「壊れないための
        // 唯一の選択」であり曖昧な分岐ではないため(feedback-ambiguity-ask-user.md参照)。
        //
        // 実際の書き込みプローブ(I/O)はProbeWorkRootWritable、フォールバック順序の
        // 判定ロジック(I/Oなし・単体試験可能)はWorkRootResolveLogic(ファイル末尾寄り、
        // PathHealthFacts等と同じ理由でMainFormの外に独立させてある)。

        /// <summary>実際にディレクトリを作成し、一時ファイルを書いて消せるかで書き込み可否を
        /// 判定する(New-Item -ItemType Directory -Force $Out と同じ失敗モードを、実行前に
        /// 検知する)。書き込めればnull、書き込めなければ例外メッセージを返す。</summary>
        internal static string ProbeWorkRootWritable(string dir)
        {
            try
            {
                Directory.CreateDirectory(dir);
                string probe = Path.Combine(dir, ".write_probe_" + Guid.NewGuid().ToString("N") + ".tmp");
                File.WriteAllText(probe, "ok", new UTF8Encoding(false));
                File.Delete(probe);
                return null;
            }
            catch (Exception ex)
            {
                return ex.GetType().Name + ": " + ex.Message;
            }
        }

        internal static bool CheckWorkRootFallbackLogic(string outDir, out List<string> problems)
        {
            problems = new List<string>();

            // case1(基準点): 主系(appRoot\work)が書き込み可能 -> 主系をそのまま使う。
            // フォールバック先へは一切触れない(不要な書き込み可否チェックをしないこと自体も確認)
            {
                bool fallbackProbed = false;
                var res = WorkRootResolveLogic.Resolve("C:\\primary", "C:\\fallback", p =>
                {
                    if (p == "C:\\fallback") fallbackProbed = true;
                    return null;
                });
                if (res.UsedFallback) problems.Add("case1(primary writable): unexpectedly used fallback");
                if (res.Failed) problems.Add("case1: unexpectedly Failed");
                if (res.Path != "C:\\primary") problems.Add("case1: expected Path=primary, got " + res.Path);
                if (fallbackProbed) problems.Add("case1: fallback should not be probed when primary succeeds");
            }

            // case2(負の対照、実報告R7GJY5W3相当): 主系が書き込み不可(Program Files配下を
            // モック) -> 自動的にフォールバックへ切り替わり、主系のエラー文言も保持されること
            {
                var res = WorkRootResolveLogic.Resolve(
                    "C:\\Program Files\\Uchinoko_for_Palworld\\work", "C:\\fallback",
                    p => p.StartsWith("C:\\Program Files", StringComparison.Ordinal)
                        ? "UnauthorizedAccessException: Access to the path is denied." : null);
                if (!res.UsedFallback) problems.Add("case2(primary unwritable): expected fallback to be used");
                if (res.Failed) problems.Add("case2: unexpectedly Failed");
                if (res.Path != "C:\\fallback") problems.Add("case2: expected Path=fallback, got " + res.Path);
                if (res.PrimaryError == null
                    || res.PrimaryError.IndexOf("Denied", StringComparison.OrdinalIgnoreCase) < 0)
                    problems.Add("case2: primary error text not carried through: " + res.PrimaryError);
            }

            // case3(負の対照): 主系・フォールバック先の両方が書き込み不可 -> Failed=trueで
            // 明確に報告し、両方のエラー文言が残ること。Pathはnullを返さない(呼び出し側の
            // 以降のPath.Combine等がNullReferenceExceptionで死なないための安全なデフォルト)
            {
                var res = WorkRootResolveLogic.Resolve("C:\\primary", "C:\\fallback", p => "Access is denied");
                if (!res.Failed) problems.Add("case3(both unwritable): expected Failed=true");
                if (res.PrimaryError == null || res.FallbackError == null)
                    problems.Add("case3: expected both PrimaryError and FallbackError to be recorded");
                if (string.IsNullOrEmpty(res.Path))
                    problems.Add("case3: Path should not be null/empty even on failure (safe default)");
            }

            // case4(実I/O、基準点): 実際に書き込み可能な一時フォルダはエラー無し判定になること
            {
                string real = Path.Combine(outDir, "real_writable_probe");
                string err = ProbeWorkRootWritable(real);
                if (err != null) problems.Add("case4(real writable dir): unexpected probe error: " + err);
                if (!Directory.Exists(real)) problems.Add("case4: probe should have created the directory");
                if (Directory.Exists(real))
                    foreach (string f in Directory.GetFiles(real))
                        problems.Add("case4: probe left a stray file behind (should self-clean): " + f);
            }

            // case5(実I/O、負の対照): 存在しないドライブレターの配下は書き込み不可と
            // 判定されること(実在するドライブだと偽陽性になるので、実在しない時だけ検査する)
            {
                if (!Directory.Exists("Z:\\"))
                {
                    string err = ProbeWorkRootWritable("Z:\\__d2p_nonexistent_drive_probe__\\work");
                    if (err == null)
                        problems.Add("case5(nonexistent drive): expected probe to fail, but it reported success");
                }
            }

            return problems.Count == 0;
        }

        static void CheckWorkRootFallbackCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckWorkRootFallbackLogic(outDir, out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== work root fallback logic unit table (dev#298) ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "work_root_fallback_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "WORK_ROOT_FALLBACK_CHECK_OK" : "WORK_ROOT_FALLBACK_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        // FIX38(2026-07-31): dev#216 WP1の「--check-self-update」隠しCLIと
        // CheckSelfUpdateLogic/CheckSelfUpdateCli/BuildFakeDistZip(自己更新の
        // ダウンロード・検証・展開・pending.json書き込みロジックの単体表)は、
        // 検査対象のSelfUpdateクラス自体を削除したためまとめて削除した
        // (FIX36: 適用エンジンがランチャー廃止で配布物から消え、ダウンロードした
        // 内容を適用する者がいなくなっていた)。復活防止テストは
        // tests\shipcheck\test_selfupdate_removed.py へ移した。

        // ---------------- dev#173: 言語切替の即時反映(ApplyLanguage)単体検査(隠しCLI) ----------------
        // 使い方: Uchinoko.exe --check-apply-language <出力先dir>
        //
        // MainFormをヘッドレスに1個生成し(画面は一切出さない。--emit-wiring/
        // --check-palworld-compat等と同じ手口)、ApplyLanguage(Lang.En) を呼んだ結果
        // 実際に画面のText/Tooltipが英語辞書へ切り替わっていること(正の対照)、
        // 続けて ApplyLanguage(Lang.Ja) で日本語へ戻ること(負の対照: 一度切り替えたら
        // 固着して戻らない退行を検出する)を5言語共通の1経路で確認する。
        // 登録数が異常に少ない場合(RegisterI18nText/RegisterI18nTipの配線漏れ)も
        // FAILにする。
        internal static bool CheckApplyLanguageLogic(out List<string> problems)
        {
            problems = new List<string>();
            var form = new MainForm();
            string paksProbeDir = null;
            try
            {
                // dev#317(2026-07-30): hosted CIでこの検査がTimeoutExpired(60秒→180秒でも
                // 解消せず)していた真因。ApplyLanguage()はUpdateAppliedStatus()経由で
                // PaksDir()(3205行目)を呼ぶが、PaksDir()は自動探索に失敗すると
                // FolderBrowserDialogを**モーダル表示してユーザー入力を待つ**
                // (1926行目のコメント「PaksDir()は自動探索/ダイアログにより時間がかかる
                // ことがある」がまさにこの箇所。WriteJob()は同じ理由でダイアログを
                // 出さないPaksDirQuiet()を使っている)。開発機ではPalworldが実在する/
                // settings_paksdir.txtが残っているため自動探索が成功しダイアログへ
                // 到達しないが、hosted CIの新規checkoutにはどちらも無いため
                // ShowDialog()が非対話プロセスを永久にブロックしていた
                // (TimeoutExpiredの正体は「遅延」ではなく「無人環境でのモーダル
                // ダイアログ待ち」)。本番のPaksDir()自体は変更しない(実ユーザーに
                // とってこのフォールバックは意図した挙動)。この検査はheadless
                // (Application.Run()を呼ばずMainFormを直接操作する)前提なので、
                // 他の検査(CheckBlenderSetupDecisionLogicのform.appRoot/blenderReady等)と
                // 同様にダミーの検体を用意してPaksDir()の最短経路
                // (paksDirCacheキャッシュヒット)だけを通す形で隔離する。
                paksProbeDir = Path.Combine(Path.GetTempPath(),
                    "d2p_apply_language_paks_probe_" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(paksProbeDir);
                File.WriteAllBytes(Path.Combine(paksProbeDir, PalWindowsPakName), new byte[] { 0 });
                form.paksDirCache = paksProbeDir;

                // 配線漏れの検出: ソース中の RegisterI18nText/RegisterI18nTip 呼び出し数
                // (定義行を除く実際の呼び出し箇所、2026-07-29時点で19/12件)と厳密に一致する
                // ことを確認する。閾値ではなく厳密一致にしているのは、1箇所だけ登録漏れが
                // あっても(=そのコントロールだけ切り替わらない退行)閾値判定だと他の
                // コントロールの登録数に紛れて検出できないため(実測: convertButton1個の
                // 登録漏れは「15件以上」の閾値では素通りしてしまい、実際にこの単体表で
                // 検出できなかった。2026-07-29 負の対照で確認済み)。
                // 新しいコントロールを追加してRegisterI18n*を呼ぶ場合は、この期待値も
                // 一緒に更新すること(dev#216 WP1でupdateNowButtonのText/Tip登録を追加し
                // 19/12 -> 20/13、dev#216 WP2でupdateRevertButtonのText/Tip登録を追加し
                // 20/13 -> 21/14、FIX38(2026-07-31)でupdateRevertButton自体を削除し
                // 21/14 -> 20/13へ戻した)
                const int expectedTextRegistrations = 20;
                const int expectedTipRegistrations = 13;
                if (form.i18nTextControls.Count != expectedTextRegistrations)
                    problems.Add("i18nTextControls登録数が期待値と不一致(配線漏れ/重複の疑い): expected="
                        + expectedTextRegistrations + " actual=" + form.i18nTextControls.Count);
                if (form.i18nTooltipControls.Count != expectedTipRegistrations)
                    problems.Add("i18nTooltipControls登録数が期待値と不一致(配線漏れ/重複の疑い): expected="
                        + expectedTipRegistrations + " actual=" + form.i18nTooltipControls.Count);

                CheckApplyLanguageOneWay(form, Lang.En, problems);
                // 負の対照: 一度Enへ切り替えた後、Jaへ戻して本当に戻ることを確認する
                // (どちらのLangでも同じ経路(ApplyLanguage)を通るだけで言語ごとの
                // 分岐は書いていないので、これは経路自体の往復検査になる)
                CheckApplyLanguageOneWay(form, Lang.Ja, problems);
                // dev#173裁定: 「反映は次回起動時」の記述はもう嘘になったので、
                // ユーザー向け文言(TipLanguageSwitch)から取り除けているかも確認する
                foreach (Lang lang in new[] { Lang.Ja, Lang.En, Lang.Ko, Lang.ZhTW, Lang.ZhCN })
                {
                    string tip = Strings.S("TipLanguageSwitch", lang);
                    if (tip.IndexOf("次回起動", StringComparison.Ordinal) >= 0
                        || tip.IndexOf("restart", StringComparison.OrdinalIgnoreCase) >= 0
                        || tip.IndexOf("다음 실행", StringComparison.Ordinal) >= 0
                        || tip.IndexOf("重新啟動", StringComparison.Ordinal) >= 0
                        || tip.IndexOf("重启", StringComparison.Ordinal) >= 0)
                        problems.Add("TipLanguageSwitch(" + lang + ")にまだ再起動前提の文言が残っている: " + tip);
                }
            }
            finally
            {
                form.Dispose();
                if (paksProbeDir != null)
                {
                    try { Directory.Delete(paksProbeDir, true); } catch (Exception) { }
                }
            }
            return problems.Count == 0;
        }

        static void AssertText(Control c, string key, Lang lang, List<string> problems)
        {
            string expected = Strings.Table[key][(int)lang];
            if (c.Text != expected)
                problems.Add("ApplyLanguage(" + lang + ")後にText不一致(直接参照): control=" + c.Name
                    + " key=" + key + " expected=" + expected + " actual=" + c.Text);
        }

        // 1方向ぶんの検査(ApplyLanguage(lang)後、登録済み全コントロールが
        // Strings.Table[key][lang] と一致するか)。往復検査(正/負の対照)の共通部分
        static void CheckApplyLanguageOneWay(MainForm form, Lang lang, List<string> problems)
        {
            form.ApplyLanguage(lang);

            if (Strings.Current != lang)
                problems.Add("ApplyLanguage(" + lang + ")後もStrings.Currentが更新されていない: " + Strings.Current);

            string expectedSubtitle = Strings.Table["TitleSubtitle"][(int)lang];
            if (form.Text.IndexOf(expectedSubtitle, StringComparison.Ordinal) < 0)
                problems.Add("ApplyLanguage(" + lang + ")後もウィンドウタイトルへ未反映: " + form.Text);

            foreach (KeyValuePair<Control, string> kv in form.i18nTextControls)
            {
                string expected = Strings.Table[kv.Value][(int)lang];
                if (kv.Key.Text != expected)
                    problems.Add("ApplyLanguage(" + lang + ")後にText不一致: key=" + kv.Value
                        + " expected=" + expected + " actual=" + kv.Key.Text);
            }
            foreach (KeyValuePair<Control, string> kv in form.i18nTooltipControls)
            {
                string expected = Strings.Table[kv.Value][(int)lang];
                string actual = form.tip.GetToolTip(kv.Key);
                if (actual != expected)
                    problems.Add("ApplyLanguage(" + lang + ")後にTooltip不一致: key=" + kv.Value
                        + " expected=" + expected + " actual=" + actual);
            }

            // 主要ボタン(フィールドとして直接参照できるもの)は、登録簿経由の一般検査に
            // 加えてピンポイントでも確認する(登録簿自体に誤ったキーが入る/別コントロールに
            // 登録される、といった一般検査では拾いにくい取り違えの保険)
            AssertText(form.convertButton, "BtnFullConvert", lang, problems);
            AssertText(form.cancelButton, "BtnCancelConvert", lang, problems);
            AssertText(form.matsButton, "BtnMatsOnly", lang, problems);
            AssertText(form.previewButton, "BtnPreviewUpdate", lang, problems);
            AssertText(form.applyButton, "BtnApply", lang, problems);
            AssertText(form.removeButton, "BtnRemoveMod", lang, problems);
            AssertText(form.deleteButton, "BtnDeleteResult", lang, problems);
            AssertText(form.reportButton, "BtnReport", lang, problems);
            AssertText(form.updateNowButton, "BtnUpdateNow", lang, problems);
            AssertText(form.autoApplyCheck, "CheckAutoApply", lang, problems);
            AssertText(form.blenderRetryButton, "BtnBlenderRetry", lang, problems);

            if (form.pakList.Columns.Count == 4)
            {
                string[] colKeys = { "ColAvatar", "ColFile", "ColSize", "ColCreatedAt" };
                for (int i = 0; i < colKeys.Length; i++)
                {
                    string expected = Strings.Table[colKeys[i]][(int)lang];
                    if (form.pakList.Columns[i].Text != expected)
                        problems.Add("ApplyLanguage(" + lang + ")後にpakList列見出し不一致: key=" + colKeys[i]
                            + " expected=" + expected + " actual=" + form.pakList.Columns[i].Text);
                }
            }
            else
            {
                problems.Add("pakList.Columns.Countが想定の4ではない: " + form.pakList.Columns.Count);
            }

            string expectedToggle = (form.kodawariPanel.Visible ? "▲" : "▼") + " "
                + Strings.Table["LabelKodawari"][(int)lang];
            if (form.kodawariToggle.Text != expectedToggle)
                problems.Add("ApplyLanguage(" + lang + ")後にkodawariToggle不一致: expected=" + expectedToggle
                    + " actual=" + form.kodawariToggle.Text);
        }

        static void CheckApplyLanguageCli(string outDir)
        {
            Directory.CreateDirectory(outDir);
            List<string> problems;
            bool ok = CheckApplyLanguageLogic(out problems);
            var sb = new StringBuilder();
            sb.AppendLine("=== ApplyLanguage (dev#173) unit table ===");
            sb.AppendLine("result=" + (ok ? "PASS" : "FAIL"));
            foreach (string p in problems) sb.AppendLine("  " + p);
            File.WriteAllText(Path.Combine(outDir, "apply_language_check.txt"), sb.ToString(), new UTF8Encoding(false));
            Console.WriteLine(ok ? "APPLY_LANGUAGE_CHECK_OK" : "APPLY_LANGUAGE_CHECK_FAIL");
            Environment.Exit(ok ? 0 : 1);
        }

        [STAThread]
        public static void Main()
        {
            string[] cmdArgs = Environment.GetCommandLineArgs();
            for (int i = 1; i < cmdArgs.Length; i++)
            {
                if (string.Equals(cmdArgs[i], "--emit-wiring", StringComparison.OrdinalIgnoreCase)
                    && i + 2 < cmdArgs.Length)
                {
                    EmitWiring(cmdArgs[i + 1], cmdArgs[i + 2]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--send-report", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    SendReportCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-i18n", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckI18nCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-palworld-compat", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckPalworldCompatCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-other-pak", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckOtherPakCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-path-health", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckPathHealthCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-work-root-fallback", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckWorkRootFallbackCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-apply-language", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckApplyLanguageCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-blender-setup-decision", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckBlenderSetupDecisionCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-dist-channel", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckDistChannelCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-sanitize-clipboard", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckSanitizeForClipboardCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-progress-relay", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckProgressRelayCli(cmdArgs[i + 1]);
                    return;
                }
                if (string.Equals(cmdArgs[i], "--check-progress-label-i18n", StringComparison.OrdinalIgnoreCase)
                    && i + 1 < cmdArgs.Length)
                {
                    CheckProgressLabelI18nCli(cmdArgs[i + 1]);
                    return;
                }
            }
            Application.EnableVisualStyles();
            Application.Run(new MainForm());
        }
    }

    // ================================================================================
    // dev#87/#89/#91(wp878991、2026-07-29): Palworld版違い警告の擬陽性解消。
    // ----------------------------------------------------------------------------
    // MainFormから独立させたのは、--check-palworld-compat隠しCLI(MainForm.
    // CheckPalworldCompatLogic参照)から画面を出さずに単体試験できるようにするため
    // (既存の--check-i18nと同じ動機)。ネットワークI/O・ファイルI/Oは一切含まない
    // 純粋な判定ロジックだけをここに置く(I/O自体はMainForm側、詳細は下記)。
    //
    // 3階層の判定(Evaluate()がMainForm.CheckPalworldVersionOnce()から呼ばれる順):
    //   1) 既知版番号(known_versions: Steam buildid + Pal-Windows.pakサイズの組)。
    //      pipeline\py\known_good_palworld.json(同梱)が持つ。判定にpak本体は
    //      一切読まない(buildid/pakサイズはMainForm.DetectPalworldVersion()が
    //      Steamのappmanifest/ファイルサイズから軽量に取得済みの値)。
    //   2) 抽出物マニフェスト(known_vanilla_manifest_sha256、dev#91)。
    //      pipeline\py\extract_vanilla.pyが書くvanilla_manifest.jsonのcombined_hash
    //      と比較する。版番号が未知でも、実際に変換が消費する材料が既知良好と
    //      一致していれば警告を出さない(層理論の互換プローブ、dev#91)。
    //      manifestは起動直後に自動で走るwarm-cache(MainForm.
    //      WarmSharedCacheOnStartup)がwork\_warm_dummy\vanilla\vanilla_manifest.json
    //      へ書く(既存の_sync_job_local_copyがそのままコピーするので新規の
    //      複製経路は追加していない)。
    //   3) どちらにも一致しなければ警告する(旧来の1)だけの判定と同じ安全側)。
    //
    // dev#89: known_versions/known_vanilla_manifest_sha256 は同梱データ(bundled)に
    // 加えて dl.osakishokai.com/versions.json の任意フィールド"palworld_known_good"
    // でも拡張できる(MergeKnownGood)。取得失敗・オフラインならbundledのみに
    // フォールバックする(remoteBlockJsonOrNull=nullを渡すだけで安全に縮退する)。
    // ================================================================================
    internal struct KnownPalworldVersion
    {
        public string BuildId;
        public long PakSize;
        public string Label;
    }

    internal class KnownGoodPalworld
    {
        public List<KnownPalworldVersion> Versions = new List<KnownPalworldVersion>();
        public List<string> ManifestHashes = new List<string>();
    }

    /// <summary>1回分のバージョン検出結果(I/O抜きの値だけ)。Paksが見つからなければ
    /// Detectedがfalseのまま(従来の「判定不能=黙って動く」を表す)。</summary>
    internal struct PalworldDetection
    {
        public bool Detected;
        public string BuildId;   // 取得できなければnull
        public long PakSize;     // 取得できなければ0
    }

    /// <summary>PalworldCompat.Evaluate()の結果。ShouldWarnがtrueの時だけ警告を出す。</summary>
    internal struct PalworldCompatStatus
    {
        public bool Detected;
        public string BuildId;
        public long PakSize;
        public bool KnownVersion;
        public string VersionLabel;
        public bool ManifestAvailable;
        public string ManifestHash;
        public bool KnownManifest;
        public bool ShouldWarn;
    }

    internal static class PalworldCompat
    {
        internal static List<KnownPalworldVersion> ParseKnownVersions(string json)
        {
            var list = new List<KnownPalworldVersion>();
            if (string.IsNullOrEmpty(json)) return list;
            var arr = Regex.Match(json, "\"known_versions\"\\s*:\\s*\\[(.*?)\\]", RegexOptions.Singleline);
            if (!arr.Success) return list;
            foreach (Match obj in Regex.Matches(arr.Groups[1].Value, "\\{[^{}]*\\}"))
            {
                string body = obj.Value;
                string buildId = MainForm.JsonStr(body, "build_id");
                double pakSize = MainForm.JsonNum(body, "pak_size", -1);
                if (string.IsNullOrEmpty(buildId) || pakSize < 0) continue;
                string label = MainForm.JsonStr(body, "label");
                list.Add(new KnownPalworldVersion
                {
                    BuildId = buildId,
                    PakSize = (long)pakSize,
                    Label = string.IsNullOrEmpty(label) ? buildId : label
                });
            }
            return list;
        }

        internal static List<string> ParseKnownManifestHashes(string json)
        {
            return MainForm.JsonStrArray(json, "known_vanilla_manifest_sha256") ?? new List<string>();
        }

        /// <summary>同梱データ(bundledJson)にリモート(remoteBlockJsonOrNull、versions.jsonの
        /// "palworld_known_good"部分だけを既に切り出したもの)を重複除去しつつ足し込む。
        /// remoteBlockJsonOrNullがnull/空なら同梱データのみ(dev#89のオフラインフォールバック)。</summary>
        internal static KnownGoodPalworld MergeKnownGood(string bundledJson, string remoteBlockJsonOrNull)
        {
            var result = new KnownGoodPalworld();
            result.Versions.AddRange(ParseKnownVersions(bundledJson));
            result.ManifestHashes.AddRange(ParseKnownManifestHashes(bundledJson));
            if (!string.IsNullOrEmpty(remoteBlockJsonOrNull))
            {
                foreach (var v in ParseKnownVersions(remoteBlockJsonOrNull))
                {
                    bool dup = false;
                    foreach (var existing in result.Versions)
                        if (existing.BuildId == v.BuildId && existing.PakSize == v.PakSize) { dup = true; break; }
                    if (!dup) result.Versions.Add(v);
                }
                foreach (var h in ParseKnownManifestHashes(remoteBlockJsonOrNull))
                    if (!result.ManifestHashes.Contains(h)) result.ManifestHashes.Add(h);
            }
            return result;
        }

        internal static bool IsKnownVersion(KnownGoodPalworld known, string buildId, long pakSize)
        {
            if (string.IsNullOrEmpty(buildId)) return false;
            foreach (var v in known.Versions)
                if (v.BuildId == buildId && v.PakSize == pakSize) return true;
            return false;
        }

        internal static string LabelFor(KnownGoodPalworld known, string buildId, long pakSize)
        {
            foreach (var v in known.Versions)
                if (v.BuildId == buildId && v.PakSize == pakSize) return v.Label;
            return null;
        }

        internal static bool IsKnownManifest(KnownGoodPalworld known, string manifestHash)
        {
            if (string.IsNullOrEmpty(manifestHash)) return false;
            foreach (var h in known.ManifestHashes)
                if (string.Equals(h, manifestHash, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        internal static string SupportedLabelsJoined(KnownGoodPalworld known)
        {
            var labels = new List<string>();
            foreach (var v in known.Versions)
                if (!labels.Contains(v.Label)) labels.Add(v.Label);
            return labels.Count > 0 ? string.Join(", ", labels) : "(none)";
        }

        /// <summary>純粋なロジックのみ(I/Oなし)。manifestHashは呼び出し側が既に読み込んだ値
        /// (無ければnull)を渡す。判定不能(Paksが見つからない)ならDetected=falseのまま返す。</summary>
        internal static PalworldCompatStatus Evaluate(KnownGoodPalworld known,
            PalworldDetection det, string manifestHash)
        {
            var st = new PalworldCompatStatus
            {
                Detected = det.Detected,
                BuildId = det.BuildId,
                PakSize = det.PakSize
            };
            if (!det.Detected) { st.ShouldWarn = false; return st; }

            if (det.BuildId != null && IsKnownVersion(known, det.BuildId, det.PakSize))
            {
                st.KnownVersion = true;
                st.VersionLabel = LabelFor(known, det.BuildId, det.PakSize);
                st.ShouldWarn = false;
                return st;
            }
            // 保険経路: buildidが取れない環境でも、pakサイズだけでも既知の値に一致すれば
            // 十分とする(旧PalworldVersionWarning()のサイズ保険と同じ考え方)
            if (det.BuildId == null && det.PakSize > 0)
            {
                foreach (var v in known.Versions)
                {
                    if (v.PakSize == det.PakSize)
                    {
                        st.KnownVersion = true;
                        st.VersionLabel = v.Label;
                        st.ShouldWarn = false;
                        return st;
                    }
                }
            }

            if (!string.IsNullOrEmpty(manifestHash))
            {
                st.ManifestAvailable = true;
                st.ManifestHash = manifestHash;
                if (IsKnownManifest(known, manifestHash))
                {
                    st.KnownManifest = true;
                    st.ShouldWarn = false;
                    return st;
                }
            }

            st.ShouldWarn = true;
            return st;
        }

        internal static string FormatDetected(PalworldCompatStatus st)
        {
            if (!st.Detected) return "not found";
            if (st.BuildId != null && st.PakSize > 0)
                return "build " + st.BuildId + ", pak "
                    + st.PakSize.ToString("N0", CultureInfo.InvariantCulture) + " bytes";
            if (st.BuildId != null) return "build " + st.BuildId;
            if (st.PakSize > 0)
                return "pak " + st.PakSize.ToString("N0", CultureInfo.InvariantCulture) + " bytes";
            return "unknown";
        }

        internal static string FormatSupported(KnownGoodPalworld known)
        {
            var parts = new List<string>();
            foreach (var v in known.Versions) parts.Add(v.Label + " (build " + v.BuildId + ")");
            return parts.Count > 0 ? string.Join(", ", parts) : "(none)";
        }

        /// <summary>dev#87: 診断ログヘッダ用の1行。検出成否・版番号・マニフェスト自己判定
        /// の結果を必ず数字入りで残す(検出失敗時も"not found"の事実を残す)。</summary>
        internal static string BuildLogLine(KnownGoodPalworld known, PalworldCompatStatus st)
        {
            string supported = FormatSupported(known);
            if (!st.Detected) return "palworld: not found (supported: " + supported + ")";
            if (st.KnownVersion)
                return "palworld: " + st.VersionLabel + " (build " + st.BuildId + ") (supported: " + supported + ")";
            string note = st.ManifestAvailable
                ? (st.KnownManifest
                    ? "extracted materials match known-good, warning suppressed (dev#91)"
                    : "extracted materials differ from known-good")
                : "extraction manifest not available yet";
            return "palworld: unknown (" + FormatDetected(st) + ") (supported: " + supported + ") [" + note + "]";
        }
    }

    // ================================================================================
    // dev#134(rd_125第14案 → 2026-07-29ぱん裁定でボタン案を却下、自動診断へ転換):
    // インストール/作業先パスの健全性判定。MainForm.CheckPathHealthOnStartup()/
    // BuildPathFacts()/PathHealthProblem()/PathHealthLine()参照。I/Oを含まない
    // 純粋な事実表現だけをここに置く(上のPalworldCompatと同じ理由、--check-path-health
    // 隠しCLIから実環境なしに単体試験できるようにするため)。
    // ================================================================================

    /// <summary>1つのパス(インストール先/作業先)の健全性を表す事実。
    /// pipeline\cli\convert.ps1のGet-PathFacts(非ASCII/空白/UNC/OneDrive配下/パス長)と
    /// 同じ観点をC#側の事前チェックに転用したもの(hasSpaceは対象外、理由はMainForm.
    /// BuildPathFacts直上のコメント参照)。</summary>
    internal struct PathHealthFacts
    {
        public string Label;
        public int Length;
        public bool NonAscii;
        public bool Unc;
        public bool UnderOneDrive;
    }

    // ================================================================================
    // dev#298: workRoot(appRoot\work)の書き込み可否に応じた自動フォールバック判定。
    // 実報告R7GJY5W3(C:\Program Files\配下インストールでUnauthorizedAccessException)
    // への対応。MainForm.ProbeWorkRootWritable()(実I/O)から呼ばれる想定だが、判定
    // ロジック自体はI/Oを含まない純粋関数にしてある(PathHealthFacts/PalworldCompatと
    // 同じ理由。--check-work-root-fallback隠しCLIから実ファイルシステムなしに
    // 単体試験できるようにするため)。
    // ================================================================================

    /// <summary>workRoot解決の結果。Pathは常に非null(両方失敗してもフォールバック先の
    /// パス文字列を入れておく——呼び出し側がこの後Path.Combine等を続けても
    /// NullReferenceExceptionで落ちない安全なデフォルトのため)。</summary>
    internal struct WorkRootResolution
    {
        public string Path;
        public bool UsedFallback;
        public bool Failed;           // 主系・フォールバック先ともに書き込み不可
        public string PrimaryPath;
        public string FallbackPath;
        public string PrimaryError;   // 主系が書き込めた場合はnull
        public string FallbackError;  // フォールバックを試さなかった/書き込めた場合はnull
    }

    internal static class WorkRootResolveLogic
    {
        /// <summary>primaryPathへの書き込みをprobeで試す。書ければそのまま使う。書けなければ
        /// fallbackPathを試し、書ければそちらへ切り替える(UsedFallback=true)。どちらも
        /// 書けなければFailed=trueで両方のエラーを持ち帰る(呼び出し側が明示的にユーザーへ
        /// 案内するための材料)。probeは書き込み不可を表す非nullエラー文字列、書き込み可能
        /// ならnullを返す関数(実装はMainForm.ProbeWorkRootWritable、テストではスタブに
        /// 差し替え可能)。</summary>
        internal static WorkRootResolution Resolve(string primaryPath, string fallbackPath, Func<string, string> probe)
        {
            var r = new WorkRootResolution { PrimaryPath = primaryPath, FallbackPath = fallbackPath };
            r.PrimaryError = probe(primaryPath);
            if (r.PrimaryError == null)
            {
                r.Path = primaryPath;
                return r;
            }
            r.FallbackError = probe(fallbackPath);
            if (r.FallbackError == null)
            {
                r.Path = fallbackPath;
                r.UsedFallback = true;
                return r;
            }
            r.Failed = true;
            // 両方失敗でも下流コードが安全に動けるよう、フォールバック先のパス文字列だけは残す
            // (実際には書き込めないが、Directory.CreateDirectory等の呼び出しは例外を投げるだけで
            // アプリ全体がクラッシュするわけではない。UpdateButtonStatesがworkRootFailedを見て
            // 変換系ボタンを無効化し、CheckPathHealthOnStartupが明示的なエラーダイアログを出す)
            r.Path = fallbackPath;
            return r;
        }
    }

    // ================================================================================
    // FIX38(2026-07-31): dev#216 WP1で新設したSelfUpdate静的クラス(UpdateReleaseInfo/
    // UpdateStageResult/IsTrustedCdnUrl/GithubReleaseFallbackUrl/VerifyFile/
    // DownloadWithFallback/ExtractAndHealthCheck/WritePendingJson/
    // ClearVerifyPendingSignal/StageUpdate)を丸ごと削除した。
    //
    // 理由: このクラスが実装していたのは「CDN→GitHub Releasesの順でダウンロード・
    // SHA256+サイズ検証・zip展開・staging作成・pending.json書き込み」までで、
    // それを読んで実際にファイルを入れ替える適用エンジン(旧app\Launcher.csの
    // ApplyEngine)は、2026-07-31のランチャー廃止で配布物から既に除去されていた。
    // つまり「ダウンロードして、検証して、ファイルを書いて、何もしない」という
    // 不活性なコードだけが残っていた(内部の実測・対照実験で、この種の
    // ダウンロード経路自体がAVのML判定を誘発しうる疑わしい特徴として
    // 指摘されている)。
    //
    // 「今すぐ更新」ボタン(updateNowButton)は、ダウンロードする代わりに
    // updateLabelと同じくOpenUpdateDownloadPage()で配布ページを開くだけに変更した
    // (FIX25推奨案。手動更新への誘導は失われず、ユーザーが押したときに実際に
    // 何かが起きるようになった)。起動時のバージョン確認(CheckForUpdateOnStartup、
    // versions.jsonをGETして新版の有無を知らせるだけの機能)はこのWPの対象外で
    // 変更していない。
    // ================================================================================
}
