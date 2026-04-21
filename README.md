分层架构：
parser：输入文档解析，提取数据
router：根据提取到的box/pin来决定去哪个website
mapper：将输入文档中提取到的数据做不同website的映射
adapter：执行网页自动化操作
writer：执行自动化写入template的操作


进度：
1. template_writer 中还有比较逻辑（写入哪个 worksheet、OD(max)、ID(min)、B22-B25） - pending
2. pots_doc_parser - coating也可以从pots doc中提取 - pending
3. template_writer 中 write（Top_thread相关单元格）和format操作需要完善 - pending
4. partner_router - 如果overall length > 18，还需要获取Drift size（要求 < ID(min)）
5. vam_mapper 还有字段（MF、Grade）匹配逻辑没有实现，等待list - pending