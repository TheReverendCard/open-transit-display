import base64,io,json,subprocess,tempfile,unittest
from pathlib import Path
from PIL import ImageFont
from build_fonts import generate,layout_sizes,rasterize,DEFAULT_CHARS
ROOT=Path(__file__).resolve().parents[2]
class FontTests(unittest.TestCase):
 def test_layout_ranges(self):
  layout=json.loads((ROOT/'firmware/layouts/site-default.json').read_text());sizes=layout_sizes(layout)
  self.assertIn(108,sizes['bold']);self.assertIn(54,sizes['bold']);self.assertIn(12,sizes['regular']);self.assertIn(11,sizes['bold'])
 def test_conversion_and_cpp(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);layout={'schema_version':'2.0','blocks':[{'type':'route','font':24,'minimum':23,'bold':True,'visible':True}]};path=root/'layout.json';path.write_text(json.dumps(layout));out=root/'generated'
   a=generate(path,ROOT/'firmware/fonts/sources.json',out);b=generate(path,ROOT/'firmware/fonts/sources.json',out)
   self.assertEqual(a,b);self.assertIn(ord('ā'),a['codepoints']);self.assertIn(ord('ū'),a['codepoints']);self.assertEqual(len(a['faces']),2)
   cpp=root/'test.cpp';cpp.write_text('''#include <cassert>
#include "transit_fonts.h"
#include "transit_font_renderer.h"
struct Pixels {int count=0;void drawPixel(int x,int y,unsigned short){assert(x>=0&&x<100&&y>=0&&y<40);++count;}};
int main(){const auto* f=transitFindFont(transit_fonts,transit_font_count,true,24);assert(f);assert(!transitFindFont(transit_fonts,transit_font_count,true,99));assert(transitGlyph(*f,0x101));assert(transitGlyph(*f,0x16b));assert(transitMeasureQ6(*f,"Whangārei")>0);const char* malformed="\\xf0\\x80";assert(transitNextCodepoint(malformed)=='?');Pixels p;transitDrawText(p,*f,"āēīōū → 216E",0,28,0,{0,0,100,40});assert(p.count>0);const char* m="ā";assert(transitNextCodepoint(m)==0x101);assert(!*m);return 0;}''')
   exe=root/'test';subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(ROOT/'firmware/fonts'),'-I'+str(out),str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
 def test_corruption_fails(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);spec=json.loads((ROOT/'firmware/fonts/sources.json').read_text());spec['fonts']['bold']['sha256']='bad'
   for f in spec['fonts'].values():f['file']=str(ROOT/'firmware/fonts'/f['file'])
   sources=p/'sources.json';sources.write_text(json.dumps(spec));layout=p/'layout.json';layout.write_text(json.dumps({'schema_version':'2.0','blocks':[{'type':'route','font':12,'minimum':12}]}))
   with self.assertRaises(ValueError):generate(layout,sources,p/'out')
 def test_glyph_bitmap(self):
  raw=base64.b64decode((ROOT/'firmware/fonts/source/display-sans-bold.otf.b64').read_bytes());font=ImageFont.truetype(io.BytesIO(raw),32)
  for ch in 'āēīōūĀĒĪŌŪ→—':
   g,b=rasterize(font,ch);self.assertGreater(g['width'],0);self.assertTrue(any(b));self.assertEqual(len(b),(g['width']*g['height']+7)//8)
  g,b=rasterize(font,' ');self.assertGreater(g['advance_q6'],0);self.assertEqual(len(b),0)
if __name__=='__main__':unittest.main()
