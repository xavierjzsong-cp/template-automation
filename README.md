分层架构：
parser：输入文档解析，提取数据
router：根据提取到的box/pin来决定去哪个website
mapper：将输入文档中提取到的数据做不同website的映射
adapter：执行网页自动化操作
writer：执行自动化写入template的操作


进度：
1. template_writer 中还有比较逻辑（写入哪个 worksheet）、write（三个 coating）和format操作需要完善
2. pots_doc_parser - 三个 coating 也可以根据从 pots doc 中提取（提取规则）然后对照映射表（需建立）
3. vam_mapper - 还有 MF（映射表需要设计）、Grade（暂不考虑）匹配逻辑没有实现
4. jfe_adapter - Grade 的匹配逻辑还需更新，目前只能匹配13CR(80)


待解决：
1. Vam 中 Material Family 如何做映射 ？（VAM中：Carbon Steel / Deep well / NA ）
2. coating 如何做映射 ？（什么情况下选择哪种 feature）
3. 如果有必要，JFE / SLHT 网页中的 Material Famlily 又是如何映射的 ？

prompt：
现在来实现一个基本的将 coating 写入 template 的逻辑：
1. 需要创建一个 coating 的 mapping 表
2. 根据 mapping 表，决定使用哪一种 coating，然后将对应的值填入 template 的单元格中
首先先实现 mapping 表的构建和写入逻辑，具体的决定逻辑后面再实现。
写入逻辑如下：
Top thread 的 coating 写入 B29，Bottom thread 的 coating 写入 B31，body 的 coating 写入 B32