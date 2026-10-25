from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

PAPER = RGBColor(247, 245, 238)
WHITE = RGBColor(255, 255, 255)
INK = RGBColor(36, 39, 30)
MUTED = RGBColor(120, 123, 110)
ACCENT = RGBColor(235, 84, 46)
SUBTLE = RGBColor(232, 236, 217)
LINE = RGBColor(223, 223, 211)

def add_background(slide, color=PAPER):
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_textbox(slide, left, top, width, height, text, font_size=18, font_color=INK, bold=False, font_name='Libre Caslon Display'):
    txBox = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = font_color
    p.font.bold = bold
    p.font.name = font_name
    p.space_after = Pt(4)
    return tf

def add_card(slide, left, top, width, height, title, body, title_color=INK, body_color=MUTED):
    shape = slide.shapes.add_shape(1, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = WHITE
    shape.line.color.rgb = LINE
    shape.line.width = Pt(1)
    shape.shadow.inherit = False
    tf = shape.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = title_color
    p.font.name = 'Libre Caslon Display'
    p.margin_top = Pt(4)
    p2 = tf.add_paragraph()
    p2.text = body
    p2.font.size = Pt(16)
    p2.font.color.rgb = body_color
    p2.font.name = 'DM Sans'
    p2.space_before = Pt(12)
    return tf

# SLIDE 1: Title
slide1 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide1)
add_textbox(slide1, 1.5, 2.0, 10.3, 3.5,
    'Supervised, Unsupervised &\nReinforcement Learning Techniques',
    font_size=44, bold=True, font_color=INK)
add_textbox(slide1, 1.5, 5.2, 10.3, 1.0,
    'Beyond the obvious: industry use cases that matter',
    font_size=22, font_color=MUTED)

# SLIDE 2: Framework Overview
slide2 = prs.slides.add_slide(prs.slide_layouts[6])
add_textbox(slide2, 0.8, 0.5, 11.7, 0.8,
    'Three Core Paradigms', font_size=32, bold=True, font_color=INK)
add_textbox(slide2, 0.8, 1.3, 11.7, 0.5,
    'How we learn from data (labeled, unlabeled, and interactive)',
    font_size=16, font_color=MUTED)

card_data = [
    ('Supervised', 'Labelled data \u2192 predict y from x', 'Image classification, fraud detection, diagnostic prediction'),
    ('Unsupervised', 'Discover structure without labels', 'Clustering, dimensionality reduction, anomaly detection'),
    ('Reinforcement', 'Learn from reward interaction', 'Robotics, game AI, resource optimization'),
]

for i, (title, desc, example) in enumerate(card_data):
    c = add_card(slide2, 1.0 + i*4.0, 2.3, 3.7, 2.2, title, desc, ACCENT, MUTED)
    add_textbox(slide2, 1.0 + i*4.0 + 0.3, 2.3 + 0.7, 3.1, 1.2,
        example, font_size=13, font_color=SUBTLE)

# SLIDE 3: Supervised Use Cases
slide3 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide3, PAPER)
add_textbox(slide3, 0.8, 0.5, 11.7, 0.8,
    'Supervised Learning: Real-World Applications',
    font_size=30, bold=True, font_color=INK)
add_textbox(slide3, 0.8, 1.1, 11.7, 0.5,
    'Excluding the ubiquitous spam filter',
    font_size=14, font_color=MUTED)

usecases_supervised = [
    ('Semiconductor Floorplanning', 'Placement cost minimization across billion-transistor designs using regression models'),
    ('Diagnostic Prediction from Imaging', 'Labeled MRI/CT volumes \u2192 disease risk scores for early intervention'),
    ('Demand Forecasting with Exogenous Variables', 'Retail price elasticity + weather + calendar features \u2192 optimized inventory'),
]

for i, (title, desc) in enumerate(usecases_supervised):
    c = add_card(slide3, 0.8 + i*4.2, 2.0, 3.7, 2.0, title, desc, ACCENT, MUTED)

# SLIDE 4: Unsupervised Use Cases
slide4 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide4, PAPER)
add_textbox(slide4, 0.8, 0.5, 11.7, 0.8,
    'Unsupervised Learning: Real-World Applications',
    font_size=30, bold=True, font_color=INK)
add_textbox(slide4, 0.8, 1.1, 11.7, 0.5,
    'Discovering structure where no labels exist',
    font_size=14, font_color=MUTED)

usecases_unsupervised = [
    ('Molecular Retrosynthesis', 'Cluster pathways from failed synthesis experiments \u2192 predict viable routes'),
    ('Seismic Fault Detection', 'Unlabeled geophone arrays \u2192 identify fault line anomalies via density estimation'),
    ('Customer Segment Discovery', 'Behavioral clustering from transaction logs \u2192 micro-segments for hyper-targeted ops'),
]

for i, (title, desc) in enumerate(usecases_unsupervised):
    c = add_card(slide4, 0.8 + i*4.2, 2.0, 3.7, 2.0, title, desc, ACCENT, MUTED)

# SLIDE 5: RL Use Cases
slide5 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide5, PAPER)
add_textbox(slide5, 0.8, 0.5, 11.7, 0.8,
    'Reinforcement Learning: Real-World Applications',
    font_size=30, bold=True, font_color=INK)
add_textbox(slide5, 0.8, 1.1, 11.7, 0.5,
    'Learning optimal policies through reward signals',
    font_size=14, font_color=MUTED)

usecases_rl = [
    ('Automated Portfolio Rebalancing', 'MDP policy \u2192 trade execution minimizing transaction costs + market impact'),
    ('Warehouse Robot Fleet Coordination', 'Multi-agent RL \u2192 collision-free picking & sorting in dynamic environments'),
    ('Industrial Process Optimization', 'Continuous control \u2192 reduce energy consumption in HVAC/manufacturing'),
]

for i, (title, desc) in enumerate(usecases_rl):
    c = add_card(slide5, 0.8 + i*4.2, 2.0, 3.7, 2.0, title, desc, ACCENT, MUTED)

# SLIDE 6: Hybrid Pipelines
slide6 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide6, PAPER)
add_textbox(slide6, 0.8, 0.5, 11.7, 0.8,
    'Hybrid Pipelines: Stitching the Three Paradigms',
    font_size=30, bold=True, font_color=INK)
add_textbox(slide6, 0.8, 1.1, 11.7, 0.5,
    'From raw data \u2192 curated features \u2192 model selection \u2192 policy deployment',
    font_size=14, font_color=MUTED)

shape = slide6.shapes.add_shape(1, Inches(0.8), Inches(2.0), Inches(11.7), Inches(3.0))
shape.fill.solid()
shape.fill.fore_color.rgb = WHITE
shape.line.color.rgb = LINE
shape.line.width = Pt(1)
tf = shape.text_frame
tf.word_wrap = True
tf.margin_left = Pt(20)
tf.margin_right = Pt(20)
p = tf.paragraphs[0]
p.text = 'Supervised \u2192 Feature Engineering \u2192 Unsupervised Discovery \u2192 RL Policy Deployment'
p.font.size = Pt(24)
p.font.bold = True
p.font.color.rgb = INK
p.font.name = 'Libre Caslon Display'
p.space_after = Pt(16)
p2 = tf.add_paragraph()
p2.text = 'Example: Labeled defect images \u2192 cluster defect types \u2192 RL agent selects optimal remediation'
p2.font.size = Pt(18)
p2.font.color.rgb = MUTED
p2.space_before = Pt(24)

# SLIDE 7: Workflow
slide7 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide7, PAPER)
add_textbox(slide7, 0.8, 0.5, 11.7, 0.8,
    'Typical Workflow',
    font_size=30, bold=True, font_color=INK)
add_textbox(slide7, 0.8, 1.1, 11.7, 0.5,
    'From data collection to deployed policy',
    font_size=14, font_color=MUTED)

steps = [
    ('Data Acquisition', 'Collect raw signals, logs, sensor readings'),
    ('Feature Curate', 'Label a subset, engineer features, reduce dimensionality'),
    ('Model Selection', 'Supervised baselines \u2192 unsupervised clusters \u2192 RL policy prototyping'),
    ('Validation', 'Cross-validation, silhouette scores, reward horizon testing'),
    ('Deployment', 'Deploy best model/policy \u2190 monitor drift, schedule retraining'),
]

for i, (title, desc) in enumerate(steps):
    y = 2.0 + i*0.9
    add_textbox(slide7, 1.2, y, 3.0, 0.7, title, font_size=16, bold=True, font_color=INK)
    add_textbox(slide7, 4.2, y, 8.1, 0.7, desc, font_size=14, font_color=MUTED)

# SLIDE 8: Conclusion
slide8 = prs.slides.add_slide(prs.slide_layouts[6])
add_background(slide8, PAPER)
add_textbox(slide8, 1.5, 1.5, 10.3, 1.5,
    'Conclusion & Next Steps',
    font_size=36, bold=True, font_color=INK, font_name='Libre Caslon Display')
add_textbox(slide8, 1.5, 3.3, 10.3, 1.5,
    '\u2022 Start with labelled data you already have \u2192 build a supervised baseline\n'
    '\u2022 Use unsupervised clustering to discover hidden patterns in your full dataset\n'
    '\u2022 Progress to RL when you have a reward signal and can simulate or interact with the environment\n'
    '\u2022 Hybrid pipelines are where real ROI lives: stitch paradigms to solve end-to-end problems',
    font_size=18, font_color=MUTED)
add_textbox(slide8, 1.5, 5.3, 10.3, 0.8,
    'Case studies & datasets available on request',
    font_size=16, font_color=SUBTLE)

output_path = Path('/home/parth/projects/presentations/ml-paradigms/ml_learning_paradigms.pptx')
prs.save(output_path)
print(f'PPTX saved: {output_path} ({output_path.stat().st_size} bytes)')