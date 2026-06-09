分层架构：
parser：输入文档解析，提取数据
router：根据提取到的box/pin来决定去哪个website
mapper：将输入文档中提取到的数据做不同website的映射
adapter：执行网页自动化操作
writer：执行自动化写入template的操作


进度：
1. template_writer 中还有比较逻辑（写入哪个 worksheet）需要完善
2. UI 界面可以美化