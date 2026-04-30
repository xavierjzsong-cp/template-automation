分层架构：
parser：输入文档解析，提取数据
router：根据提取到的box/pin来决定去哪个website
mapper：将输入文档中提取到的数据做不同website的映射
adapter：执行网页自动化操作
writer：执行自动化写入template的操作


进度：
1. template_writer 中还有比较逻辑（写入哪个 worksheet）、write（thread的length、coating相关、Drift size（要求 < ID(min)））和format操作需要完善
2. pots_doc_parser - coating 也可以从 pots doc 中提取
3. tsh_adapter - 还需要添加 EL & IL、Drift size 的抓取逻辑
4. vam_adapter - 还需要添加 Drift size 的抓取逻辑
5. vam_mapper 还有字段（MF、Grade）匹配逻辑没有实现，等待 list
6. tsh_mapper - Grade 字段目前是 hardcode