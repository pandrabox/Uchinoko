<!-- TODO(v2.3.0, 2026-08-01): 日本語正本(manual.md)の以下の変更が未反映(訳文未作成)。
  [済 2026-08-01 wp/audit-doc-rest] 1) 起動手順: Uchinoko.exe → Uchinoko.bat のダブルクリックに変更。初回の「発行元を確認できません」系警告は「開く」でよい旨を追記
  2) 冒頭に v2.3.0 の見た目変更の注記(ボタン配置と操作手順は従来同一・SSは順次更新)を追加
  [済 2026-08-01 wp/audit-doc-rest] 3) Blender手動配置先を res\assets\tools\blender-4.3.2-windows-x64\ に変更(旧v2.2.x以前の場所は括弧書きで併記)
  4) SmartScreen節を削除し、AV(セキュリティソフト)節を事実記述のみの短文(警告・削除事象の報告があった/v2.3.0はexe非同梱構成/問題時は問合せへ)に書き直し
  5) 言語切替リンク: ko/zh は公開HTML未提供のため非リンクの「準備中」表記に変更 -->

# Uchinoko for Palworld 使用方法 — VRChat 模型篇

*[日本語](manual.md) | [English](manual.en.md) | [한국어](manual.ko.md) | [繁體中文](manual.zh-TW.md)*

## 角色模型的使用方法
打开自己角色模型的 Unity 项目(可在 Unity 2022.3.22f1 上运行)。
![](img/2.webp)

将 Hierarchy 中自己的角色模型拖曳并放到 Assets 下方(这样会将其转为 prefab)。
![](img/3.webp)

在刚生成的图标上单击右键,选择「Show in Explorer」。
**退出 Unity**。
![](img/4.webp)

双击打开 Uchinoko for Palworld(Uchinoko.bat)。首次运行时可能会出现「无法验证发布者」之类的警告,选择「打开」(或「运行」)继续启动即可,没有问题。
![](img/1.webp)

**仅首次启动时**,会在后台自动下载转换所需的 Blender(约 350MB)(不会显示对话框)。准备完成前,画面下方会显示「准备中」,「完整转换」等按钮将无法点击。根据网络环境不同可能需要几分钟,请**耐心等待**。即使在准备完成前拖放文件,准备完成后也会自动处理。若进行不顺利,请参考下方的「遇到问题时」。

从资源管理器将自己角色模型的 prefab 文件拖放到 Uchinoko for Palworld 上。
![](img/5.webp)

请稍候片刻。
![](img/6.webp)

缩略图显示后,「完整转换(创建 MOD)」按钮即可点击,请点击它。
![](img/7.webp)

会显示使用条款,请确认内容后同意。
![](img/8.webp)

稍候片刻后即完成应用(请先关闭幻兽帕鲁)。
![](img/9.webp)


## 遇到问题时: 首次设置(下载 Blender)失败

由于网络连接问题等原因,首次启动时的 Blender 自动下载有时会失败。若拖放后加载一直无法完成,或因错误而停止,请先怀疑这个原因。

1. 请先确认网络连接,然后重新启动 Uchinoko for Palworld,或点击画面右下角的「重新获取 Blender」按钮。
2. 若仍然失败,可以手动准备。
   1. 从 https://www.blender.org/download/ 下载 Blender 4.3.2 的 Windows x64 版(Portable/zip)。
   2. 解压下载的 zip,将内含 `blender.exe` 的文件夹内容,直接复制到与 Uchinoko.bat 同一位置的 `res\assets\tools\blender-4.3.2-windows-x64\` 文件夹中(若文件夹不存在请自行新建。**在 v2.2.x 及更早的旧版本中,该文件夹位于可执行文件同一位置的 `assets\tools\blender-4.3.2-windows-x64\` 或 `_internal\assets\tools\blender-4.3.2-windows-x64\`**)。


## Tips

- 本转换工具是供个人使用自己的角色模型游玩的工具。不支持多人游玩等用途。
- 不支持与其他 pak MOD 并用。检测到其他 pak MOD 时会显示警告。
- 右下角的菜单可以执行多种操作。
  - 应用到幻兽帕鲁…当您转换了多个角色并想切换,或转换完成时幻兽帕鲁正在运行而未能顺利应用时使用
  - 解除 MOD…想要解除时使用
  - 刷新列表…刷新 MOD 列表
  - 删除转换结果…想删除不再需要的角色时使用
  - 问题反馈…遇到困难时使用
  - 手动复制日志…附加于问题反馈中,能帮助我们更快排解问题
