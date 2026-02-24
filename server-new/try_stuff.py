from kraken import binarization, pageseg
from PIL import Image

im = Image.open("myimg.png")
bw_im = binarization.nlbin(im)
seg = pageseg.segment(bw_im, text_direction='horizontal-lr')
print(seg['boxes'])