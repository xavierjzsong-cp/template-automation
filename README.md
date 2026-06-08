分层架构：
parser：输入文档解析，提取数据
router：根据提取到的box/pin来决定去哪个website
mapper：将输入文档中提取到的数据做不同website的映射
adapter：执行网页自动化操作
writer：执行自动化写入template的操作


进度：
1. template_writer 中还有比较逻辑（写入哪个 worksheet）、write（三个 coating）和format操作需要完善
2. vam_mapper - 还有 MF（映射表需要设计）、Grade（暂不考虑）匹配逻辑没有实现



待解决：
1. Vam 中 Material Family 如何做映射 ？（VAM中：Carbon Steel / Deep well / NA ）
2. UI 界面可以美化

prompt：
现在来实现一个基本的将 coating 写入 template 的单元格中的逻辑：
Top thread 的 coating 写入 B29，Bottom thread 的 coating 写入 B31，body 的 coating 写入 B32