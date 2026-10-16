import math
import unittest
from studio.media import _text_layer, _font

class NumericTypography(unittest.TestCase):
    def render_glyphs(self,text,highlight='',highlight_size=80):
        style={'x':0,'y':0,'w':1080,'h':220,'font':'sans','size':80,'weight':'normal','align':'left','padding':0,'line_height':1.28,'color':'#ffffff','outline_width':0,'background_opacity':0}
        emphasis=dict(style,size=highlight_size)
        layer=_text_layer(text,style,emphasis,highlight,[],'검증')
        cursor=0;bounds=[]
        for index,c in enumerate(text):
            font=_font(emphasis if c in highlight else style,[])
            width=font.getlength(c)
            box=layer.crop((math.ceil(cursor)+1,0,math.floor(cursor+width)-1,220)).getbbox()
            bounds.append(box)
            cursor+=width
        return bounds

    def test_decimal_point_stays_near_numeric_baseline(self):
        digit,point,*_=self.render_glyphs('3.07%')
        self.assertGreater(point[1],(digit[1]+digit[3])/2)
        self.assertLessEqual(abs(point[3]-digit[3]),2)

    def test_comma_descends_below_digits(self):
        digit,comma,*_=self.render_glyphs('1,000,000')
        self.assertGreater(comma[1],(digit[1]+digit[3])/2)
        self.assertGreater(comma[3],digit[3])

    def test_middle_dot_is_between_caps_top_and_baseline(self):
        caps,dot,*_=self.render_glyphs('A·A')
        self.assertGreater(dot[1],caps[1]+5)
        self.assertLess(dot[3],caps[3]-5)

    def test_different_highlight_size_shares_numeric_baseline(self):
        digit,point,large,*_=self.render_glyphs('3.07%','07',120)
        self.assertGreater(point[1],(digit[1]+digit[3])/2)
        self.assertLessEqual(abs(large[3]-digit[3]),2)

if __name__=='__main__': unittest.main(verbosity=2)
