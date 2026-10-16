// 自托管字体(私有本地部署不外连 Google Fonts)。
// 拉丁字形用 @fontsource 打包进产物;中文字形走 tokens.css 字体栈里的系统字体
// (Noto Sans/Serif SC 若本机已装仍优先命中,否则 PingFang / 微软雅黑 / 宋体)。
// CJK 的 @fontsource 包体积过大(每族 70MB+),故不打包。
import '@fontsource/noto-sans/400.css';
import '@fontsource/noto-sans/500.css';
import '@fontsource/noto-sans/600.css';
import '@fontsource/noto-sans/700.css';
import '@fontsource/noto-serif/400.css';
import '@fontsource/noto-serif/500.css';
import '@fontsource/noto-serif/600.css';
import '@fontsource/noto-serif/700.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
