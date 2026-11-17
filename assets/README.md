# assets/

`watermark.ttf` — шрифт водяного знака демо-версії (`demo.py`): підмножина DejaVu Sans Bold лише з літерами
напису «Демо · Yalott Studio» і цифрами, ~19 КБ. Вкладено в репозиторій, щоб водяний знак із кирилицею
працював на будь-якому сервері, навіть без встановлених шрифтів.

Ліцензія DejaVu Fonts (на основі Bitstream Vera) дозволяє вільно використовувати, змінювати й поширювати шрифт:
https://dejavu-fonts.github.io/License.html

Змінили напис водяного знака (`demo.WATERMARK_TEXT`)? Перегенеруйте підмножину з потрібними літерами
(fontTools: `pyftsubset DejaVuSans-Bold.ttf --text="…" --output-file=watermark.ttf`) і збільште
`demo.WATERMARK_VERSION`, щоб кеш фото перемалювався.
