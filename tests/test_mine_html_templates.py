import random
import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from olmocr.bench.synth.mine_html_templates import (
    PreserveTablesConverter,
    extract_html_metadata,
    generate_tests_from_html,
    html_to_markdown_with_frontmatter,
)
from olmocr.bench.tests import TestType


class TestMineTests(unittest.TestCase):
    def setUp(self):
        self.random_generator = random.Random(42)
        return super().setUp()

    def test_absent_nested(self):
        html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Paradigm for Nuclear Safety</title>
</head>
<body>
    <header>
        <div class="logo" aria-label="Japan Nuclear Safety Institute Logo"></div>
    </header>
    
    <main>
        <h1>New Paradigm for Nuclear Safety</h1>
        
        <div class="attribution">
            <p>Thursday, April 25, 2013</p>
            <p>Japan Nuclear Safety Institute</p>
            <p>Shojiro Matsuura, Chairman</p>
        </div>
    </main>
    
    <footer>
        <div class="footer-line"></div>
        <div class="footer-content">
            <div class="footer-text">
                <p class="tagline">In Pursuit of Improved Nuclear Safety</p>
                <p class="copyright">Copyright © 2012 by Japan Nuclear Safety Institute. All Rights Reserved.</p>
            </div>
            <div class="footer-logo" aria-label="Japan Nuclear Safety Institute Logo"></div>
        </div>
    </footer>
</body>
"""
        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)

        self.assertEqual(len([test for test in tests if test["type"] == "absent"]), 2)

    def test_text_basic(self):
        html_content = """

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bone Morphology Description</title>
</head>
<body>
    <main>
        <p>The posterior end exhibits a curved process to articulate with the angular. Aside from the process, the rest of the posterior end has slight curvatures for articulation, but is mostly uniform. Ventral border of the bone is mostly straight, with slight curvature (FIG. 20).</p>
        
        <p><span class="section-heading">Lateral</span>- A spine runs from the anterior-most tip, reduces in height ~3/4 way down toward posterior, and terminates at the center of the posterior notch. A fossa is present on the dorsal side of the spine. The posterior end exhibits more relief than in medial view, with the medial side of the posterior process extending past the posterior notch.</p>
        
        <p><span class="section-heading">Ontogeny</span>- Anterior tip is sharply pointed in AR12 and AR1 with AR2 being rounded, though this could be due to breakage. Anterior dorsal margin is straight and flat in AR12; AR2 shows little curvature and AR1 shows the most curvature; curving outward dorsally. Dorsal incisure is anteroposteriorly oriented in AR12, in AR2 there is some ventral curvature, and in AR1 there is a posteroventral curvature. Both AR1 and AR3 are curved on the ventral margin while AR12 is mostly straight. Posterior end of AR1 exhibits four undulations, ventral process is not yet extended. A fossa is present dorsal to the ventral process, not seen on AR12 or AR2. In medial view the lateral ridge is visible posteriorly in AR1 and AR2l the ridge does not fully extend anteriorly. In lateral view of the posterior the ventral process is present on AR2, but not fully extended posteriorly. Tip of the anterodorsal process is sharply pointed in AR1 and AR2, rounded in AR12. A short ridge is present on the dorsal edge of the dorsal process of AR1. The short ridge on the posterodorsal process of AR2 is slightly more ventral than in AR1. On AR12 the ridge is long and positioned most ventral. The lateral ridge is closest to the ventral margin in AR1. In AR2 the ridge is positioned more dorsally and in AR12 the ridge terminates and the anterior tip. The section of bone ventral to the lateral ridge appears to thin with age. The posterior notch on AR12 is curved anteriorly and the medial side of the notch extends posteriorly</p>
    </main>
    
    <footer>
        <p>46</p>
    </footer>
</body>
</html>"""

        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)
        self.assertGreater(len(tests), 5)

    def test_big_headers(self):
        html_content = """

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FORANE 427A Comparative Data</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 724px;
            margin: 0 auto;
            padding: 20px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        
        table, th, td {
            border: 1px solid black;
        }
        
        th, td {
            padding: 8px;
            text-align: left;
        }
        
        th {
            background-color: #f2f2f2;
        }
        
        .logo {
            width: 150px;
            height: 80px;
            background-color: #eee;
            border: 1px solid #000;
            margin-top: 20px;
        }
        
        footer {
            margin-top: 40px;
            font-size: 0.8em;
        }
        
        .company-info {
            margin-top: 20px;
            display: flex;
            justify-content: space-between;
        }
        
        .contact {
            text-align: right;
        }
    </style>
</head>
<body>
    <header>
        <h1>Comparative data</h1>
    </header>
    
    <main>
        <table>
            <thead>
                <tr>
                    <th>Parameters</th>
                    <th>R-22</th>
                    <th>FORANE<sup>®</sup> 427A</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Evaporating temperature</td>
                    <td>2.7 °C</td>
                    <td>1.1 °C</td>
                </tr>
                <tr>
                    <td>Condensing temperature</td>
                    <td>40.3 °C</td>
                    <td>44.0 °C</td>
                </tr>
                <tr>
                    <td>Suction temperature</td>
                    <td>7.1 °C</td>
                    <td>9.2 °C</td>
                </tr>
                <tr>
                    <td>Suction pressure</td>
                    <td>5.4 bar</td>
                    <td>5.0 bar</td>
                </tr>
                <tr>
                    <td>Discharge temperature</td>
                    <td>69.5 °C</td>
                    <td>71.1 °C</td>
                </tr>
                <tr>
                    <td>Discharge pressure</td>
                    <td>15.5 bar</td>
                    <td>17.1 bar</td>
                </tr>
                <tr>
                    <td>Cooling power</td>
                    <td>431 KW</td>
                    <td>376 KW</td>
                </tr>
                <tr>
                    <td>Power consumption</td>
                    <td>122 kW</td>
                    <td>124 kW</td>
                </tr>
                <tr>
                    <td>Residual mineral oil</td>
                    <td>-</td>
                    <td>11%</td>
                </tr>
            </tbody>
        </table>
        
        <p>During this field test, very satisfactory running conditions were reached immediately. The temperature set points were easily achieved with similar energy consumption as compared to R-22 despite a high level of residual mineral oil in the circuit. The performance of the installation continues to satisfy the customer's requirements after more than one year of service.</p>
        
        <p>FORANE<sup>®</sup> 427A consequently fully satisfies the requirements of the European regulations while enabling existing equipment to continue to perform well without the need for any long and costly plant modifications.</p>
        
        <p>The versatility of FORANE<sup>®</sup> 427A is also appreciated as it can be used to retrofit low temperature refrigeration equipment as well as air-conditioning installations, resulting in only one retrofit refrigerant for all R-22 units.</p>
        
        <p>Combining environmental friendliness, high performance and simplicity is today a reality with FORANE<sup>®</sup> 427A !</p>
    </main>
    
    <footer>
        <p>The information contained in this document is based on trials carried out by our Research Centres and data selected from the literature, but shall in no event be held to constitute or imply any warranty, undertaking, express or implied commitment from our part. Our formal specifications define the limit of our commitment. No liability whatsoever can be accepted by Arkema with regard to the handling, processing or use of the product or products concerned which must in all cases be employed in accordance with all relevant laws and/or regulations in force in the country or countries concerned.</p>
        
        <div class="company-info">
            <div class="address">
                <div class="logo"></div>
                <p>ARKEMA<br>
                420 rue d'Estienne d'Orves<br>
                92700 Colombes - France<br>
                www.arkema.com</p>
            </div>
            
            <div class="contact">
                <p>www.forane.com / info.forane@arkema.com</p>
            </div>
        </div>
    </footer>
</body>
</html>"""

        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)

        self.assertFalse(any(test for test in tests if test["type"] == "absent" and "Comparative data" in test["text"]))

    def test_page_num(self):
        html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Academic Paper - Page 47</title>
</head>
<body>
    <main>
        <div class="image" aria-label="Bar Plot for supportprotest comparing data from 2020 and 2023, showing different levels of support from 'Don't know/No answer' to 'Strongly disagree'"></div>
        
        <p class="figure-caption">Figure 4.3: The COVID-19 pandemic resulted in meaningful increase in the support for other groups' protests among Panamanians.</p>
        
        <section>
            <h2>4.2.2 Demographically-Informed Opinion Assignment</h2>
            
            <p>Our model does not endow opinions randomly; instead, we leverage data to assign activists in a more realistic fashion. We use Latinobarómetro survey data from 2020 and 2023, both of which contain the three measurements of support for protest. Then, we explored which demographic groups were more likely to be activists; these are young adults and individuals at either extreme of the financial spectrum. We use this insight to influence the assignment of opinions: our logistic equations make it so that individuals with these characteristics are more likely to be labeled as activists as the probabilistic endowment happens. The code ensures that the proportion of activists overall remains exactly as desired and that there are activists who do not belong to these identified groups</p>
        </section>
        
        <section>
            <h2>4.2.3 Identity Factored into Social Influence</h2>
            
            <p>The similarity formula for Panama is built as follows, taking in nine demographic factors stored as node attributes. These are gender, age, nationality, financial status, highest level of education, level of employment, geographical region, party affiliation, and ethnicity (respectively encoded as gend, age, nation, fin, edu, emp, region, paff, and ethni). Each one of these factors has an associated weight; in this model, all factors were weighted as 0.10, except for level of education and financial status which received 0.15. Our code establishes logical rules to compare the two individuals on each dimension and return a factor by which to multiply the weight. These factors can be absolute or relative, based on the demographic dimension in question. For example, the logical conditions for gender returns 1 if same or 0 if different, while age returns a float value between 0 and 1 according to how close in age the individuals are. Once the pairwise similarity</p>
        </section>
    </main>
    
    <footer>
        <p>47</p>
    </footer>
</body>
</html>"""

        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)

        self.assertEqual(len([test for test in tests if test["type"] == "absent"]), 1)

    def test_div_footer(self):
        html_content = """

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Being Thai: A Narrow Identity in a Wide World</title>
    <style>
        body {
            font-family: Times New Roman, serif;
            line-height: 1.5;
            max-width: 710px;
            margin: 0 auto;
            padding: 20px;
        }
        .color-bars {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        .left-bar, .right-bar {
            height: 20px;
            width: 200px;
            border: 1px solid #000;
        }
        .left-bar {
            background: linear-gradient(to right, #000, #fff);
        }
        .right-bar {
            background: linear-gradient(to right, yellow, magenta, cyan, green, blue, red, black, yellow, pink, lightblue);
        }
        .page-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        h1 {
            font-size: 1.5em;
            margin-top: 30px;
            margin-bottom: 20px;
        }
        .footnote {
            font-size: 0.8em;
            vertical-align: super;
        }
        ol {
            margin-left: 20px;
        }
        .page-footer {
            display: flex;
            justify-content: space-between;
            margin-top: 40px;
            font-size: 0.8em;
            color: #666;
        }
        .registration-mark {
            font-size: 1.2em;
            color: #000;
        }
    </style>
</head>
<body>
    <div class="color-bars">
        <div class="left-bar"></div>
        <span class="registration-mark">⊕</span>
        <div class="right-bar"></div>
    </div>

    <div class="page-header">
        <div>Being Thai: A Narrow Identity in a Wide World</div>
        <div>333</div>
    </div>

    <p>hard to create a political and cultural narrative that appeals to old ideas about being Thai at this moment of perceived vulnerability.</p>

    <h1>The Concept of "Thainess"</h1>

    <p>Thainess is a political notion that originally evolved to support an authoritarian government and was then re-shaped for periods of more democratic rule.<span class="footnote">13</span> Thailand has long oscillated between dictatorship and democracy and, in either case, a sense of the "Thai style" (<em>baeb Thai</em>) is commonly invoked. Under these conditions a military coup may be thought to "advance Thai-style democracy".<span class="footnote">14</span> This is obviously fraught with difficulties and requires government agencies, most notably the Ministry of Culture, to work hard on shaping national identity.<span class="footnote">15</span> Thailand's geographical and cultural diversity means that there are inevitable deviations. Some of these have been astutely handled, especially in the northeastern provinces where the Lao-speaking minority has been integrated as <em>chao isan</em>. Nowadays it is only at the margins that their "Isan-ness" remains a contested sub-category of Thainess.<span class="footnote">16</span> In earlier generations there were more explicit challenges to the suggestion of Isan as Thai.<span class="footnote">17</span> Similar defiance has emerged in both the northern provinces<span class="footnote">18</span> and in the Malay Muslim majority areas of the far south.<span class="footnote">19</span> At various times there have been suggestions, as reported by the anthropologist Nick Tapp, that "Thainess" was disintegrating.<span class="footnote">20</span> It is in response to these persistent challenges that Prayuth's military government has sought to create its own revised version of the national ideal.</p>

    <p>For the military government the codification of Thailand's core values has created new opportunities to stamp its preferred identity on society. In a key speech soon after he took power in 2014, Prayuth identified disunity as a problem in Thai society that would, in his words, "urgently require inclusive cooperation from people of all levels, gender and age".<span class="footnote">21</span> His approach was to "define clear core values of Thai people so that we can build a strong nation". These values draw on cultural ideas that have existed for many decades and have enjoyed the favour of previous military rulers. The full list of these twelve values is:</p>

    <ol>
        <li>Upholding the three main pillars of the country: the nation, the religion and the monarchy;</li>
        <li>Showing honesty, sacrifice and patience, with a positive attitude for the interest of the public;</li>
        <li>Practicing filial piety towards parents, guardians and teachers;</li>
        <li>Seeking both direct and indirect knowledge and education;</li>
    </ol>

    <div class="registration-mark" style="position: absolute; left: 10px; bottom: 50%;">⊕</div>
    <div class="registration-mark" style="position: absolute; right: 10px; bottom: 50%;">⊕</div>

    <div class="page-footer">
        <div>15-03450 10a Thailand.indd 333</div>
        <div>15/2/16 8:24 am</div>
    </div>
</body>
</html>"""

        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)

        self.assertEqual(len([test for test in tests if test["type"] == "absent"]), 4)

    def test_table(self):
        html_content = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Distribuição da população na estrutura socioocupacional - Brasil 2000</title>
    <style>
        body {
            font-family: Times New Roman, serif;
            line-height: 1.4;
            max-width: 686px;
            margin: 0 auto;
        }
        header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        th, td {
            border: 1px solid black;
            padding: 2px 4px;
            text-align: center;
        }
        th {
            font-weight: bold;
        }
        .left-align {
            text-align: left;
        }
        .source {
            font-size: 0.8rem;
            font-style: italic;
            margin-top: 10px;
        }
        footer {
            margin-top: 20px;
            font-size: 0.8rem;
            text-align: center;
        }
    </style>
</head>
<body>
    <header>
        <div></div>
        <div>Alexandre Gori Maia e Waldir José de Quadros ■ 417</div>
    </header>

    <h3>Apêndice A - Distribuição da população na estrutura socioocupacional - Brasil 2000</h3>

    <table>
        <thead>
            <tr>
                <th rowspan="2" class="left-align">Grupo Ocupacional</th>
                <th rowspan="2" class="left-align">Classe Ocupacional</th>
                <th colspan="2">Superior</th>
                <th colspan="2">Médio</th>
                <th colspan="2">Baixo</th>
                <th colspan="2">Interior</th>
                <th colspan="2">Ínfimo</th>
                <th colspan="2">Total</th>
            </tr>
            <tr>
                <th>N (1.000s)</th>
                <th>%</th>
                <th>N (1.000s)</th>
                <th>%</th>
                <th>N (1.000s)</th>
                <th>%</th>
                <th>N (1.000s)</th>
                <th>%</th>
                <th>N (1.000s)</th>
                <th>%</th>
                <th>N (1.000s)</th>
                <th>%</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td rowspan="3" class="left-align">Empregadores</td>
                <td class="left-align">A-1 Empregadores (> 10)</td>
                <td>608</td>
                <td>67,3</td>
                <td>185</td>
                <td>20,4</td>
                <td>86</td>
                <td>9,6</td>
                <td>16</td>
                <td>1,8</td>
                <td>8</td>
                <td>0,9</td>
                <td>903</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">A-2 Empregadores (<= 10)</td>
                <td>1.555</td>
                <td>36,9</td>
                <td>1.107</td>
                <td>26,3</td>
                <td>1.036</td>
                <td>24,7</td>
                <td>341</td>
                <td>8,1</td>
                <td>171</td>
                <td>4,1</td>
                <td>4.213</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Total</td>
                <td>2.162</td>
                <td>42,3</td>
                <td>1.292</td>
                <td>25,3</td>
                <td>1.126</td>
                <td>22,0</td>
                <td>357</td>
                <td>7,0</td>
                <td>179</td>
                <td>3,5</td>
                <td>5.116</td>
                <td>100</td>
            </tr>
            <tr>
                <td rowspan="3" class="left-align">Profissionais</td>
                <td class="left-align">C Profissionais Autônomos</td>
                <td>1.643</td>
                <td>21,7</td>
                <td>1.513</td>
                <td>20,0</td>
                <td>2.073</td>
                <td>27,4</td>
                <td>1.225</td>
                <td>16,2</td>
                <td>1.108</td>
                <td>14,7</td>
                <td>7.562</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">D Profissionais Assalariados</td>
                <td>4.438</td>
                <td>13,3</td>
                <td>6.030</td>
                <td>18,0</td>
                <td>11.550</td>
                <td>34,5</td>
                <td>7.027</td>
                <td>21,0</td>
                <td>4.389</td>
                <td>13,1</td>
                <td>33.434</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Total</td>
                <td>6.081</td>
                <td>14,8</td>
                <td>7.543</td>
                <td>18,4</td>
                <td>13.623</td>
                <td>33,2</td>
                <td>8.252</td>
                <td>20,1</td>
                <td>5.497</td>
                <td>13,4</td>
                <td>40.995</td>
                <td>100</td>
            </tr>
            <tr>
                <td rowspan="4" class="left-align">Massa Não-Agrícola</td>
                <td class="left-align">F Trabalhadores Autônomos</td>
                <td>657</td>
                <td>3,5</td>
                <td>1.754</td>
                <td>9,2</td>
                <td>5.561</td>
                <td>29,2</td>
                <td>5.271</td>
                <td>27,7</td>
                <td>5.788</td>
                <td>30,4</td>
                <td>19.030</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">G Trabalhadores Assalariados</td>
                <td>282</td>
                <td>0,7</td>
                <td>1.657</td>
                <td>4,3</td>
                <td>10.363</td>
                <td>27,1</td>
                <td>13.002</td>
                <td>34,0</td>
                <td>12.968</td>
                <td>33,9</td>
                <td>38.272</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">I Trabalhadores Domésticos</td>
                <td>10</td>
                <td>0,1</td>
                <td>104</td>
                <td>1,6</td>
                <td>977</td>
                <td>14,7</td>
                <td>1.810</td>
                <td>27,3</td>
                <td>3.733</td>
                <td>56,3</td>
                <td>6.633</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Total</td>
                <td>948</td>
                <td>1,5</td>
                <td>3.515</td>
                <td>5,5</td>
                <td>16.901</td>
                <td>26,4</td>
                <td>20.083</td>
                <td>31,4</td>
                <td>22.489</td>
                <td>35,2</td>
                <td>63.936</td>
                <td>100</td>
            </tr>
            <tr>
                <td rowspan="4" class="left-align">Massa Agrícola</td>
                <td class="left-align">H-1 Proprietários Conta Própria</td>
                <td>188</td>
                <td>2,0</td>
                <td>364</td>
                <td>3,8</td>
                <td>1.387</td>
                <td>14,4</td>
                <td>1.889</td>
                <td>19,7</td>
                <td>5.779</td>
                <td>60,2</td>
                <td>9.608</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">H-2 Trabalhadores Autônomos</td>
                <td>5</td>
                <td>0,5</td>
                <td>14</td>
                <td>1,5</td>
                <td>72</td>
                <td>7,6</td>
                <td>152</td>
                <td>16,1</td>
                <td>703</td>
                <td>74,3</td>
                <td>946</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">H-3 Trabalhadores Assalariados</td>
                <td>17</td>
                <td>0,2</td>
                <td>58</td>
                <td>0,6</td>
                <td>794</td>
                <td>8,4</td>
                <td>2.260</td>
                <td>23,9</td>
                <td>6.322</td>
                <td>66,9</td>
                <td>9.451</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Total</td>
                <td>210</td>
                <td>1,0</td>
                <td>436</td>
                <td>2,2</td>
                <td>2.253</td>
                <td>11,3</td>
                <td>4.301</td>
                <td>21,5</td>
                <td>12.805</td>
                <td>64,0</td>
                <td>20.005</td>
                <td>100</td>
            </tr>
            <tr>
                <td rowspan="5" class="left-align">Não-remunerados</td>
                <td class="left-align">Não-remunerados Não-Agrícolas</td>
                <td>13</td>
                <td>6,8</td>
                <td>16</td>
                <td>8,1</td>
                <td>28</td>
                <td>14,0</td>
                <td>22</td>
                <td>10,9</td>
                <td>119</td>
                <td>60,2</td>
                <td>198</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Não-remunerados Agrícolas</td>
                <td>5</td>
                <td>0,1</td>
                <td>13</td>
                <td>0,3</td>
                <td>59</td>
                <td>1,6</td>
                <td>352</td>
                <td>9,4</td>
                <td>3.302</td>
                <td>88,5</td>
                <td>3.731</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Sem Ocupação Com Renda</td>
                <td>1.567</td>
                <td>6,0</td>
                <td>2.330</td>
                <td>8,9</td>
                <td>5.395</td>
                <td>20,7</td>
                <td>6.821</td>
                <td>26,2</td>
                <td>9.964</td>
                <td>38,2</td>
                <td>26.078</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Sem Ocupação Sem Renda</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td>8.094</td>
                <td>100</td>
                <td>8.094</td>
                <td>100</td>
            </tr>
            <tr>
                <td class="left-align">Ignorados</td>
                <td>177</td>
                <td>10,3</td>
                <td>202</td>
                <td>11,8</td>
                <td>364</td>
                <td>21,1</td>
                <td>337</td>
                <td>19,6</td>
                <td>640</td>
                <td>37,2</td>
                <td>1.720</td>
                <td>100</td>
            </tr>
        </tbody>
    </table>

    <p class="source">Fonte: Censo Demográfico 2000, microdados. IBGE. Elaboração dos autores.</p>

    <footer>
        RESR, Piracicaba, SP, vol. 47, nº 02, p. 389-418, abr/jun 2009 – Impressa em julho 2009
    </footer>
</body>
</html>"""

        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)

        self.assertTrue(len(tests) > 10)

    def test_sup(self):
        html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A ROSE BY ANY OTHER NAME</title>
    <style>
        body {
            font-family: Georgia, serif;
            line-height: 1.5;
            margin: 0 auto;
            max-width: 666px;
            padding: 20px;
        }
        header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        .page-number-left {
            text-align: left;
        }
        .title {
            text-align: center;
            font-weight: bold;
            flex-grow: 1;
        }
        .page-number-right {
            text-align: right;
        }
        .section-heading {
            text-align: center;
            margin: 20px 0;
        }
        p {
            text-indent: 2em;
            margin: 0 0 10px 0;
        }
        .footnotes {
            margin-top: 30px;
            border-top: 1px solid #ccc;
            padding-top: 10px;
            font-size: 0.9em;
        }
        .footnote {
            text-indent: -1.5em;
            padding-left: 1.5em;
            margin-bottom: 5px;
        }
        .italic {
            font-style: italic;
        }
        sup {
            font-size: 0.7em;
            vertical-align: super;
        }
    </style>
</head>
<body>
    <header>
        <div class="page-number-left">2016]</div>
        <div class="title">A ROSE BY ANY OTHER NAME</div>
        <div class="page-number-right">1083</div>
    </header>

    <main>
        <p>cases were decided within a year of each other (2000 and 2001, respectively). <span class="italic">Save the Manatee Club</span> largely consists of a truncated version of the <span class="italic">Consolidated-Tomoka</span> analysis, with minor adjustments to conform the opinion to the 1999 amendments. <span class="italic">Day Cruise</span>, on the other hand, closely analyzes the 1999 version of section 120.52(8). However, it is <span class="italic">Save the Manatee Club</span> that has come to dominate Florida court opinions on rulemaking challenges and not the more detailed <span class="italic">Day Cruise</span> analysis.<sup>78</sup> The following Sections will discuss the facts of the two cases, examine the differences between their analyses of section 120.52(8), and finally conclude with an opinion on which analysis is better to apply in section 120.52(8) rulemaking challenges.</p>

        <h2 class="section-heading">A. Southwest Florida Water Management District v. Save the Manatee Club, Inc.</h2>

        <p>After the legislature amended the APA, the First DCA analyzed the statutory language of section 120.52(8) again in <span class="italic">Southwest Florida Water Management District v. Save the Manatee Club, Inc.</span><sup>79</sup> <span class="italic">Save the Manatee Club</span> concerned the Southwest Florida Water Management District's (the "District's") authority to create exemptions to environmental resource permitting requirements.<sup>80</sup> South Shores Partners, Ltd. ("South Shores") applied "for a permit to develop a 720-acre tract of land in Southwest Hillsborough County."<sup>81</sup> As part of the development project, South Shores wanted "to build a connecting waterway between the [existing] canal system [on the property] and the [Tampa] Bay."<sup>82</sup> The Save the Manatee Club believed that the resulting increase in power boat traffic in this new waterway would "endanger the manatee and its habitat."<sup>83</sup></p>

        <p>The District has the authority to grant either a general permit or an environmental resource permit to a development project, depending on the type of project involved.<sup>84</sup> When granting an environmental resource permit, the District must consider "[t]he impact a proposed development will have on wildlife" as a factor; it does not have to do so when it grants a general permit.<sup>85</sup> The District granted South</p>
    </main>

    <footer class="footnotes">
        <div class="footnote">78. As of December 14, 2015, a search of the "Citing References" on WestLaw shows that <span class="italic">Save the Manatee Club</span> has been cited by forty court opinions. <span class="italic">Day Cruise</span>, by comparison, has been cited by fifteen court opinions. These numbers do not include citations to either case in DOAH decisions.</div>
        <div class="footnote">79. 773 So. 2d 594 (Fla. 1st DCA 2000).</div>
        <div class="footnote">80. <span class="italic">Id.</span> at 596.</div>
        <div class="footnote">81. <span class="italic">Id.</span></div>
        <div class="footnote">82. <span class="italic">Id.</span></div>
        <div class="footnote">83. <span class="italic">Id.</span></div>
        <div class="footnote">84. <span class="italic">See id.</span></div>
        <div class="footnote">85. <span class="italic">Id.</span></div>
    </footer>
</body>
</html>"""

        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)

        superscript_map = {
            "0": "⁰",
            "1": "¹",
            "2": "²",
            "3": "³",
            "4": "⁴",
            "5": "⁵",
            "6": "⁶",
            "7": "⁷",
            "8": "⁸",
            "9": "⁹",
            "+": "⁺",
            "-": "⁻",
            "=": "⁼",
            "(": "⁽",
            ")": "⁾",
            "n": "ⁿ",
            "i": "ⁱ",
        }

        for test in tests:
            for sup in superscript_map.values():
                self.assertTrue(sup not in test.get("text", ""))
                self.assertTrue(sup not in test.get("before", ""))
                self.assertTrue(sup not in test.get("after", ""))

    def test_katex_autorender(self):
        """Test that KaTeX math expressions are properly auto-rendered when using the render_pdf_with_playwright function."""
        import asyncio
        import os
        import tempfile

        from olmocr.bench.synth.mine_html_templates import render_pdf_with_playwright

        # Create HTML with LaTeX expressions
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>KaTeX Auto-Render Test</title>
        </head>
        <body>
            <h1>Math Expressions Test</h1>
            
            <p>Inline math expression: \(E = mc^2\)</p>
            
            <p>Block math expression:</p>
            <p>\[
            \\frac{d}{dx}(x^n) = nx^{n-1}
            \]</p>
            
            <p>Another complex equation:</p>
            <p>\[
            \int_{a}^{b} f(x) \, dx = F(b) - F(a)
            \]</p>
        </body>
        </html>
        """

        # Create a temporary file to store the rendered PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            output_pdf_path = tmp_file.name

        # Render the HTML to PDF
        render_success = asyncio.run(render_pdf_with_playwright(html_content=html_content, output_pdf_path=output_pdf_path, png_width=800, png_height=600))

        # Check if rendering was successful
        self.assertTrue(render_success, "PDF rendering should succeed")

        # Verify PDF was created and has content
        self.assertTrue(os.path.exists(output_pdf_path), "PDF file should exist")
        self.assertTrue(os.path.getsize(output_pdf_path) > 0, "PDF file should have content")

        # The actual validation of KaTeX rendering would require visual inspection or text extraction,
        # but at minimum we can verify the file was created successfully

        print(output_pdf_path)

    def test_line_numbers(self):
        html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>House Amendment Bill No. CS/CS/SB 7030</title>
</head>
<body>
    <header class="document-header">
        <div class="bill-title">HOUSE AMENDMENT</div>
        <div>Bill No. CS/CS/SB 7030, 1st Eng. (2019)</div>
    </header>

    <div class="amendment-label">Amendment No.</div>

    <div class="chamber-action">
        <div class="chamber-columns">
            <div class="senate-column">Senate</div>
            <div class="house-column">House</div>
        </div>
        <div style="text-align: center;">.</div>
    </div>

    <div class="horizontal-line"></div>

    <div class="horizontal-line"></div>

    <div class="amendment-content">
        <div>
            <span class="line-number">1</span>
            <div class="line-content">Representative Jenne offered the following:</div>
        </div>
        <div>
            <span class="line-number">2</span>
            <div class="line-content"></div>
        </div>
        <div>
            <span class="line-number">3</span>
            <div class="line-content"><strong>Amendment</strong></div>
        </div>
        <div>
            <span class="line-number">4</span>
            <div class="line-content">Remove lines 274-280 and insert:</div>
        </div>
        <div>
            <span class="line-number">5</span>
            <div class="line-content">c.3. Pass <span class="underline">an initial</span> a psychological evaluation, and</div>
        </div>
        <div>
            <span class="line-number">6</span>
            <div class="line-content"><span class="underline">subsequent yearly psychological evaluations before each school</span></div>
        </div>
        <div>
            <span class="line-number">7</span>
            <div class="line-content"><span class="underline">year, administered by a psychologist licensed under chapter 490</span></div>
        </div>
        <div>
            <span class="line-number">8</span>
            <div class="line-content">and designated by the Department of Law Enforcement and submit</div>
        </div>
        <div>
            <span class="line-number">9</span>
            <div class="line-content">the results of <span class="underline">such evaluations</span> <span class="strikethrough">the evaluation</span> to the sheriff's</div>
        </div>
        <div>
            <span class="line-number">10</span>
            <div class="line-content">office. The Department of Law Enforcement is authorized to</div>
        </div>
        <div>
            <span class="line-number">11</span>
            <div class="line-content">provide the sheriff's office with mental health and substance</div>
        </div>
        <div>
            <span class="line-number">12</span>
            <div class="line-content">abuse data for compliance with this paragraph.</div>
        </div>
    </div>

    <footer class="document-footer">
        <div>588513</div>
        <div>Approved For Filing: 4/23/2019 6:09:18 PM</div>
        <div>Page 1 of 1</div>
    </footer>
</body>
</html>"""

        tests = generate_tests_from_html(html_content, "0", 1, self.random_generator)

        for test in tests:
            if test["type"] == "order":
                self.assertTrue(len([c for c in test["before"] if not c.isdigit()]) > 0)


class TestMathExtraction(unittest.TestCase):
    """Test the math extraction functionality in mine_html_templates.py"""

    def setUp(self):
        self.random_generator = random.Random(42)
        return super().setUp()

    def test_math_extraction_from_html(self):
        """Test that math equations are properly extracted from HTML content"""
        html_content = """
        <html>
        <body>
        <p>Some text with inline math \\(x = 2\\) here.</p>
        <p>Display math: \\[E = mc^2\\]</p>
        <p>Another inline: \\(\\alpha + \\beta = \\gamma\\)</p>
        <p>Complex display: \\[\\int_0^\\infty e^{-x} dx = 1\\]</p>
        </body>
        </html>
        """

        # Generate tests from HTML
        tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)

        # Filter math tests
        math_tests = [t for t in tests if t.get("type") == "math"]

        # Check that we extracted math equations
        self.assertTrue(len(math_tests) > 0, "Should extract at least one math equation")

        # Check that specific equations were extracted
        math_contents = [t["math"] for t in math_tests]
        self.assertIn("x = 2", math_contents)
        self.assertIn("E = mc^2", math_contents)
        self.assertIn("\\alpha + \\beta = \\gamma", math_contents)
        self.assertIn("\\int_0^\\infty e^{-x} dx = 1", math_contents)

    def test_math_extraction_with_multiline(self):
        """Test extraction of multiline math equations"""
        html_content = """
        <html>
        <body>
        <p>Multiline equation:
        \\[
        e_i = \\frac{e_i + \\varphi(e_i)}{2} + \\frac{e_i - \\varphi(e_i)}{2}, 
        \\quad \\text{for } i \\in \\mathbb{N}.
        \\]
        </p>
        </body>
        </html>
        """

        tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)
        math_tests = [t for t in tests if t.get("type") == "math"]

        # Check multiline equation is captured
        self.assertTrue(len(math_tests) > 0)

        # Check that the multiline content is preserved (without excessive newlines)
        found_multiline = False
        for test in math_tests:
            if "\\frac{e_i + \\varphi(e_i)}{2}" in test["math"] and "\\mathbb{N}" in test["math"]:
                found_multiline = True
                break

        self.assertTrue(found_multiline, "Should extract multiline equation correctly")

    def test_math_extraction_deduplication(self):
        """Test that duplicate math equations are deduplicated"""
        html_content = """
        <html>
        <body>
        <p>First occurrence: \\[x^2 + y^2 = z^2\\]</p>
        <p>Second occurrence: \\[x^2 + y^2 = z^2\\]</p>
        <p>Third occurrence: \\[x^2 + y^2 = z^2\\]</p>
        </body>
        </html>
        """

        tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)
        math_tests = [t for t in tests if t.get("type") == "math"]

        # Count how many times the equation appears
        equation_count = sum(1 for t in math_tests if "x^2 + y^2 = z^2" in t["math"])

        # Should only appear once due to deduplication
        self.assertEqual(equation_count, 1, "Duplicate equations should be deduplicated")

    def test_math_extraction_patterns(self):
        """Test different math delimiter patterns"""
        html_content = """
        <html>
        <body>
        <p>Pattern 1: \\(inline1\\)</p>
        <p>Pattern 2: \\[display1\\]</p>
        <p>Pattern 3: $$display2$$</p>
        </body>
        </html>
        """

        tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)
        math_tests = [t for t in tests if t.get("type") == "math"]

        math_contents = [t["math"] for t in math_tests]

        # Check all patterns are captured
        self.assertIn("inline1", math_contents)
        self.assertIn("display1", math_contents)
        self.assertIn("display2", math_contents)

    def test_math_extraction_minimum_length(self):
        """Test that very short equations are filtered out"""
        html_content = """
        <html>
        <body>
        <p>Short: \\(x\\)</p>
        <p>Also short: \\[y\\]</p>
        <p>Long enough: \\(x=1\\)</p>
        </body>
        </html>
        """

        tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)
        math_tests = [t for t in tests if t.get("type") == "math"]

        math_contents = [t["math"] for t in math_tests]

        # Short equations (length <= 2) should be filtered out
        self.assertNotIn("x", math_contents)
        self.assertNotIn("y", math_contents)
        # Longer equation should be included
        self.assertIn("x=1", math_contents)

    def test_math_validation_passes(self):
        """Test that valid math tests pass validation against markdown"""
        html_content = """
        <html>
        <body>
        <p>Test equation: \\[E = mc^2\\]</p>
        </body>
        </html>
        """

        # Mock the validation to always pass for math tests
        with patch("olmocr.bench.tests.load_single_test") as mock_load:
            mock_test = MagicMock()
            mock_test.run.return_value = (True, None)
            mock_load.return_value = mock_test

            tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)
            math_tests = [t for t in tests if t.get("type") == "math"]

            # Verify math test was created
            self.assertTrue(len(math_tests) > 0)
            # Verify test has correct structure
            for test in math_tests:
                self.assertEqual(test["type"], "math")
                self.assertIn("math", test)
                self.assertEqual(test["max_diffs"], 0)
                self.assertIn("id", test)
                self.assertIn("pdf", test)
                self.assertEqual(test["page"], 1)

    def test_complex_markdown_example(self):
        """Test with the complex markdown example provided by the user"""
        # Convert markdown to HTML-like structure for testing
        html_content = '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>Automorphisms of Order Two</title>\n    <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>\n    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>\n    <script>\n        window.MathJax = {\n            tex: {\n                inlineMath: [[\'\\\\(\', \'\\\\)\']],\n                displayMath: [[\'\\\\[\', \'\\\\]\']]\n            }\n        };\n    </script>\n    <style>\n        body {\n            font-family: "Times New Roman", serif;\n            font-size: 11pt;\n            line-height: 1.4;\n            max-width: 791px;\n            margin: 0 auto;\n            padding: 20px;\n            background-color: white;\n        }\n        \n        .math-block {\n            margin: 15px 0;\n        }\n        \n        .definition {\n            margin: 20px 0;\n        }\n        \n        .definition-header {\n            font-weight: bold;\n            margin-bottom: 10px;\n        }\n        \n        .lemma {\n            margin: 20px 0;\n        }\n        \n        .lemma-header {\n            font-weight: bold;\n            margin-bottom: 10px;\n        }\n        \n        .proof {\n            margin: 15px 0;\n        }\n        \n        .proof-header {\n            font-weight: bold;\n            display: inline;\n        }\n        \n        .qed {\n            float: right;\n            font-weight: bold;\n        }\n        \n        ul {\n            margin: 15px 0;\n            padding-left: 20px;\n        }\n        \n        ol {\n            margin: 15px 0;\n            padding-left: 20px;\n        }\n        \n        h2 {\n            font-size: 14pt;\n            font-weight: bold;\n            margin: 25px 0 15px 0;\n        }\n        \n        .equation {\n            text-align: right;\n            margin: 15px 0;\n        }\n        \n        footer {\n            text-align: center;\n            margin-top: 30px;\n            font-weight: bold;\n        }\n    </style>\n</head>\n<body>\n    <div class="math-block">\n        <p>If \\(\\varphi \\in \\text{Aut}(E)\\) with \\(\\varphi^2 = id\\) we observe that</p>\n        \\[e_i = \\frac{e_i + \\varphi(e_i)}{2} + \\frac{e_i - \\varphi(e_i)}{2}, \\quad \\text{for } i \\in \\mathbb{N}.\\]\n        \n        <p>Setting \\(a_i = e_i + \\varphi(e_i)/2\\) we have:</p>\n        \n        <ul>\n            <li>\\(\\varphi(e_i) = -e_i + 2a_i\\),</li>\n            <li>\\(\\varphi(a_i) = a_i\\), that is, \\(a_i\\) is of degree zero in the \\(\\mathbb{Z}_2\\)-grading \\(E_\\varphi\\),</li>\n            <li>\\(\\varphi(e_i - a_i) = -(e_i - a_i)\\), that is, \\(e_i - a_i\\) is of degree 1 in the \\(\\mathbb{Z}_2\\)-grading \\(E_\\varphi\\).</li>\n        </ul>\n    </div>\n    \n    <div class="definition">\n        <div class="definition-header">Definition 5</div>\n        <p>Let \\(\\varphi \\in \\text{Aut}(E)\\). We say that \\(\\varphi\\) is of <em>canonical type</em> if \\(\\varphi(e_i) \\in E_{(1)}\\) for all \\(i\\).</p>\n        \n        <p>If \\(\\varphi\\) is an automorphism of order 2 on \\(E\\), we have that \\(\\varphi\\) is of canonical type if and only if \\(a_i \\in E_{(1)}\\) for all \\(i\\). Let us fix a basis \\(\\beta = \\{e_1, e_2, \\ldots, e_n, \\ldots\\}\\) of the vector space \\(L\\) and an automorphism \\(\\varphi \\in \\text{Aut}(E)\\) such that \\(\\varphi^2 = id\\). Then \\(\\varphi\\), as a linear transformation, has eigenvalues \\(\\pm 1\\) and \\(-1\\) only, and moreover, there exists a basis of the vector space \\(E\\) consisting of eigenvectors. (It is well known from elementary Linear Algebra that this fact does not depend on the dimension of the vector space as long as the characteristic of \\(F\\) is different from 2.) Then \\(E = E(1) \\oplus E(-1)\\) where \\(E(t)\\) is the eigenspace for the eigenvalue \\(t\\) of the linear transformation \\(\\varphi\\). One considers the intersections \\(L(t) = L \\cap E(t)\\), \\(t = \\pm 1\\). Changing the basis \\(\\beta\\), if necessary, one may assume that \\(L(t)\\) is the span of \\(\\beta \\cap L(t)\\). Clearly this change of basis gives rise to a homogeneous automorphism of \\(E\\) and we can take the composition of it and then \\(\\varphi\\). We shall assume that such a change of basis has been done.</p>\n        \n        <p>Denote</p>\n        \\[I_\\varphi = \\{n \\in \\mathbb{N} \\mid \\varphi(e_n) = \\pm e_n\\}.\\]\n    </div>\n    \n    <p>We shall distinguish the following four possibilities:</p>\n    \n    <ol>\n        <li>\\(I_\\varphi = \\mathbb{N}\\).</li>\n        <li>\\(I_\\varphi \\neq \\mathbb{N}\\) is infinite.</li>\n        <li>\\(I_\\varphi\\) is finite and nonempty.</li>\n        <li>\\(I_\\gamma = \\emptyset\\) for every linear basis \\(\\gamma\\) of \\(L\\).</li>\n    </ol>\n    \n    <p>We shall call these automorphisms (and also the corresponding \\(\\mathbb{Z}_2\\)-gradings), automorphisms (or gradings) of type 1, 2, 3, and 4, respectively.</p>\n    \n    <p>The automorphisms of type 1 induce \\(\\mathbb{Z}_2\\)-gradings on \\(E\\) in which all generators of \\(E\\) are homogeneous. Such structures are called homogeneous \\(\\mathbb{Z}_2\\)-gradings on \\(E\\). The corresponding graded identities were completely studied in [22, 24, 29].</p>\n    \n    <p>We conclude this section with the following lemma.</p>\n    \n    <div class="lemma">\n        <div class="lemma-header">Lemma 6</div>\n        <p>Let \\(\\varphi\\) be an automorphism of order two of \\(E\\). Then \\(\\varphi\\) is of type 4 if and only if, for every \\(v \\in L\\) such that \\(\\varphi(v) = \\pm v\\), one has \\(v = 0\\).</p>\n        \n        <div class="proof">\n            <span class="proof-header">Proof</span> Assume that \\(\\varphi\\) is of type 4 and let \\(v \\in L\\) with \\(\\varphi(v) = \\pm v\\). If \\(v \\neq 0\\), choose a basis \\(\\gamma\\) of \\(L\\) such that \\(v \\in \\gamma\\). Then \\(I_\\gamma \\neq \\emptyset\\), a contradiction. The converse follows by the same argument.\n            <span class="qed">■</span>\n        </div>\n    </div>\n    \n    <h2>3 &nbsp;&nbsp; Automorphisms of order two of <em>E</em></h2>\n    \n    <p>From this point on, our goal is to survey recent developments regarding automorphisms of order two and the corresponding \\(\\mathbb{Z}_2\\)-gradings of the infinite-dimensional Grassmann algebra.</p>\n    \n    <p>Let \\(X = \\{e_1, \\ldots, e_n, \\ldots\\}\\). For each map \\(\\lambda : X \\to E\\), we can define the linear transformation \\(\\varphi : E \\to E\\) by</p>\n    \n    <div class="equation">\n        \\[\\varphi(e_{i_1} \\cdots e_{i_n}) = \\lambda(e_{i_1}) \\cdots \\lambda(e_{i_n}),\\] <span style="float: right;">(1)</span>\n    </div>\n    \n    <p>for all \\(n \\in \\mathbb{N}\\).</p>\n    \n    <p>We start with the next lemma.</p>\n    \n    <div class="lemma">\n        <div class="lemma-header">Lemma 7</div>\n        <p><em>The linear transformation</em> \\(\\varphi\\) <em>is an endomorphism of</em> \\(E\\) <em>if and only if</em></p>\n        \\[\\lambda(e_i)\\lambda(e_j) + \\lambda(e_j)\\lambda(e_i) = 0, \\quad \\text{for all } i, j.\\]\n    </div>\n    \n    <footer>\n        4\n    </footer>\n</body>\n</html>'
        tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)
        math_tests = [t for t in tests if t.get("type") == "math"]

        for test in math_tests:
            print(test)

    def test_math_extraction_strips_whitespace(self):
        """Test that extracted math equations have whitespace properly stripped"""
        html_content = """
        <html>
        <body>
        <p>\\[
            x = y + z
        \\]</p>
        </body>
        </html>
        """

        tests = generate_tests_from_html(html_content, "test_pdf", 1, self.random_generator)
        math_tests = [t for t in tests if t.get("type") == "math"]

        self.assertTrue(len(math_tests) > 0)
        # The equation should be stripped of leading/trailing whitespace
        self.assertEqual(math_tests[0]["math"].strip(), math_tests[0]["math"])


class TestExtractHtmlMetadata(unittest.TestCase):
    def test_extract_metadata_portuguese_document(self):
        """Test metadata extraction from a Portuguese document with mixed content."""
        html_content = """
        <html lang="pt">
        <head><title>Test Document</title></head>
        <body>
            <header>Header content here</header>
            <h1>Política de Metadados</h1>
            <p>Este é um documento de teste com texto em português.</p>
            <p>Contém múltiplos parágrafos para simular conteúdo real.</p>
            <div class="image">Image placeholder 1</div>
            <p>Mais texto após a imagem.</p>
            <footer>Footer content</footer>
        </body>
        </html>
        """

        metadata = extract_html_metadata(html_content)

        # Check language extraction
        self.assertEqual(metadata["primary_language"], "pt")

        # Check rotation values (always fixed)
        self.assertTrue(metadata["is_rotation_valid"])
        self.assertEqual(metadata["rotation_correction"], 0)

        # Check table/diagram detection
        # With 1 image (500 chars) and small text content, image ratio > 50%
        self.assertFalse(metadata["is_table"])
        self.assertTrue(metadata["is_diagram"])  # Image estimate dominates

    def test_extract_metadata_table_heavy_document(self):
        """Test metadata extraction from a document that is mostly tables."""
        html_content = """
        <html lang="en">
        <body>
            <p>Small intro text</p>
            <table>
                <tr><td>Cell 1</td><td>Cell 2</td><td>Cell 3</td></tr>
                <tr><td>Data A</td><td>Data B</td><td>Data C</td></tr>
                <tr><td>More data</td><td>More data</td><td>More data</td></tr>
                <tr><td>Even more data</td><td>Even more data</td><td>Even more data</td></tr>
                <tr><td>Lots of data</td><td>Lots of data</td><td>Lots of data</td></tr>
                <tr><td>Table content</td><td>Table content</td><td>Table content</td></tr>
                <tr><td>Final row</td><td>Final row</td><td>Final row</td></tr>
            </table>
        </body>
        </html>
        """

        metadata = extract_html_metadata(html_content)

        self.assertEqual(metadata["primary_language"], "en")
        self.assertTrue(metadata["is_table"])  # Should be True as >50% is table
        self.assertFalse(metadata["is_diagram"])

    def test_extract_metadata_image_heavy_document(self):
        """Test metadata extraction from a document that is mostly images."""
        html_content = """
        <html lang="es">
        <body>
            <p>Brief text</p>
            <div class="image">Image 1</div>
            <div class="image">Image 2</div>
            <div class="image">Image 3</div>
            <div class="image">Image 4</div>
            <div class="image">Image 5</div>
        </body>
        </html>
        """

        metadata = extract_html_metadata(html_content)

        self.assertEqual(metadata["primary_language"], "es")
        self.assertFalse(metadata["is_table"])
        self.assertTrue(metadata["is_diagram"])  # Should be True as >50% is images

    def test_extract_metadata_language_with_region(self):
        """Test that language codes with regions (e.g., pt-BR) are shortened."""
        html_content = """
        <html lang="pt-BR">
        <body>
            <p>Texto em português brasileiro</p>
        </body>
        </html>
        """

        metadata = extract_html_metadata(html_content)

        # Should convert pt-BR to pt
        self.assertEqual(metadata["primary_language"], "pt")

    def test_extract_metadata_no_html_tag(self):
        """Test extraction when there's no html tag (defaults to 'en')."""
        html_content = """
        <body>
            <p>Content without html tag</p>
        </body>
        """

        metadata = extract_html_metadata(html_content)

        self.assertEqual(metadata["primary_language"], "en")  # Should default to 'en'

    def test_extract_metadata_mixed_content(self):
        """Test a document with mixed content types."""
        html_content = """<!DOCTYPE html>
                <html lang="pt-BR">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Política de Metadados para Livros e Capítulos de Livro UFPA</title>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            margin: 0;
                            padding: 20px;
                            width: 725px;
                            height: 1024px;
                            box-sizing: border-box;
                        }
                        
                        .header-logos {
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            margin-bottom: 30px;
                        }
                        
                        .image {
                            border: 2px solid black;
                            background-color: #ccc;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            color: black;
                            font-weight: bold;
                        }
                        
                        .logo-left {
                            width: 120px;
                            height: 80px;
                        }
                        
                        .logo-center {
                            width: 300px;
                            height: 80px;
                        }
                        
                        .logo-right {
                            width: 120px;
                            height: 80px;
                        }
                        
                        h1 {
                            text-align: center;
                            font-weight: bold;
                            font-size: 16px;
                            margin: 20px 0;
                            text-transform: uppercase;
                        }
                        
                        .intro-text {
                            text-align: justify;
                            margin-bottom: 20px;
                            font-size: 14px;
                            line-height: 1.4;
                        }
                        
                        table {
                            width: 100%;
                            border-collapse: collapse;
                            font-size: 12px;
                        }
                        
                        th, td {
                            border: 1px solid black;
                            padding: 8px;
                            text-align: left;
                            vertical-align: middle;
                        }
                        
                        th {
                            background-color: #f0f0f0;
                            font-weight: bold;
                            text-align: center;
                        }
                        
                        .col-metadados {
                            width: 35%;
                        }
                        
                        .col-valor {
                            width: 35%;
                        }
                        
                        .col-repetitivo {
                            width: 15%;
                            text-align: center;
                        }
                        
                        .col-condicao {
                            width: 15%;
                            text-align: center;
                        }
                        
                        footer {
                            text-align: center;
                            margin-top: 20px;
                            font-size: 14px;
                            font-weight: bold;
                        }
                    </style>
                </head>
                <body>
                    <header>
                        <div class="header-logos">
                            <div class="image logo-left">Biblioteca Central UFPA</div>
                            <div class="image logo-center">LIVRO ABERTO portal do livro aberto da UFPA</div>
                            <div class="image logo-right">SIBI/UFPA</div>
                        </div>
                    </header>

                    <main>
                        <h1>Política de Metadados para Livros e Capítulos de Livro UFPA</h1>
                        
                        <p class="intro-text">
                            Essa política de metadados possui o objetivo de garantir a consistência do trabalho executado no Portal do Livro Aberto. Dessa forma, foi desenvolvido com base no esquema de metadados do Dublin Core com adaptações para a realidade brasileira e local.
                        </p>

                        <table>
                            <thead>
                                <tr>
                                    <th class="col-metadados">METADADOS</th>
                                    <th class="col-valor">VALOR</th>
                                    <th class="col-repetitivo">REPETITIVO</th>
                                    <th class="col-condicao">CONDIÇÃO</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>dc.type</td>
                                    <td>Tipo de documento</td>
                                    <td>Não</td>
                                    <td>Obrigatório</td>
                                </tr>
                                <tr>
                                    <td>dc.title</td>
                                    <td>Título e subtítulo (se houver)</td>
                                    <td>Não</td>
                                    <td>Obrigatório</td>
                                </tr>
                                <tr>
                                    <td>dc.title.alternative</td>
                                    <td>Título alternativo</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.creator</td>
                                    <td>Autor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.creator.Lattes</td>
                                    <td>URL do currículo Lattes do autor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.creator.ORCID</td>
                                    <td>ORCID do autor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.description.affiliation</td>
                                    <td>Afiliação do autor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.organizer</td>
                                    <td>Organizador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.organizerLattes</td>
                                    <td>URL do currículo Lattes do organizador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.organizerORCID</td>
                                    <td>ORCID do organizador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.description.affiliationOrganizer</td>
                                    <td>Afiliação do organizador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.coordinator</td>
                                    <td>Coordenador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.coordinatorLattes</td>
                                    <td>URL do currículo Lattes do coordenador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.coordinatorORCID</td>
                                    <td>ORCID do coordenador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.affiliationCoordinator</td>
                                    <td>Afiliação do coordenador</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.editor</td>
                                    <td>Editor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.editorLattes</td>
                                    <td>URL do currículo Lattes do editor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.contributor.editorORCID</td>
                                    <td>ORCID do editor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                                <tr>
                                    <td>dc.description.affiliationEditor</td>
                                    <td>Afiliação do editor</td>
                                    <td>Sim</td>
                                    <td>Opcional</td>
                                </tr>
                            </tbody>
                        </table>
                    </main>

                    <footer>
                        <div>3</div>
                    </footer>
                </body>
                </html>
        """

        metadata = extract_html_metadata(html_content)

        self.assertEqual(metadata["primary_language"], "pt")
        self.assertTrue(metadata["is_table"])
        self.assertFalse(metadata["is_diagram"])

    def test_extract_metadata_empty_body(self):
        """Test extraction with empty or minimal content."""
        html_content = """
        <html lang="de">
        <body></body>
        </html>
        """

        metadata = extract_html_metadata(html_content)

        self.assertEqual(metadata["primary_language"], "de")
        self.assertFalse(metadata["is_table"])
        self.assertFalse(metadata["is_diagram"])
        self.assertTrue(metadata["is_rotation_valid"])
        self.assertEqual(metadata["rotation_correction"], 0)


class TestHtmlToMarkdown(unittest.TestCase):
    def test_title_tag_excluded_from_markdown(self):
        """Test that title tags from head are not included in markdown output."""
        html_content = """
        <html lang="en">
        <head>
            <title>This Should Not Appear In Markdown</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <h1>Main Heading</h1>
            <p>This is the body content that should appear.</p>
        </body>
        </html>
        """

        markdown_with_frontmatter = html_to_markdown_with_frontmatter(html_content)

        # Check that the title from head tag is NOT in the markdown
        self.assertNotIn("This Should Not Appear In Markdown", markdown_with_frontmatter)

        # Check that body content IS in the markdown
        self.assertIn("Main Heading", markdown_with_frontmatter)
        self.assertIn("This is the body content that should appear", markdown_with_frontmatter)

        # Check that frontmatter is present
        self.assertTrue(markdown_with_frontmatter.startswith("---"))

    def test_image_with_data_description(self):
        """Test that images are converted with placeholder alt text."""
        html_content = """
        <html lang="en">
        <body>
            <p>Text before image</p>
            <div class="image" data-description="A beautiful sunset over mountains">Placeholder</div>
            <p>Text after image</p>
        </body>
        </html>
        """

        markdown_with_frontmatter = html_to_markdown_with_frontmatter(html_content)

        # Check that images use the fixed placeholder alt text
        self.assertIn("![Image Placeholder]", markdown_with_frontmatter)

        # Check that other content is preserved
        self.assertIn("Text before image", markdown_with_frontmatter)
        self.assertIn("Text after image", markdown_with_frontmatter)

    def test_image_without_data_description(self):
        """Test that images without data-description use default alt text."""
        html_content = """
        <html lang="en">
        <body>
            <div class="image">Some placeholder content</div>
        </body>
        </html>
        """

        markdown_with_frontmatter = html_to_markdown_with_frontmatter(html_content)

        # Check that default alt text is used
        self.assertIn("![Image Placeholder]", markdown_with_frontmatter)

    def test_headers_footers_excluded(self):
        """Test that header and footer tags are excluded from markdown."""
        html_content = """
        <html lang="en">
        <body>
            <header>
                <nav>Navigation menu that should not appear</nav>
            </header>
            <main>
                <h1>Main Content</h1>
                <p>This should appear in the markdown.</p>
            </main>
            <footer>
                <p>Footer text that should not appear</p>
            </footer>
        </body>
        </html>
        """

        markdown_with_frontmatter = html_to_markdown_with_frontmatter(html_content)

        # Check that header/footer content is excluded
        self.assertNotIn("Navigation menu", markdown_with_frontmatter)
        self.assertNotIn("Footer text", markdown_with_frontmatter)

        # Check that main content is included
        self.assertIn("Main Content", markdown_with_frontmatter)
        self.assertIn("This should appear in the markdown", markdown_with_frontmatter)

    def test_no_body_tag_fallback(self):
        """Test that content is still processed when there's no body tag."""
        html_content = """
        <div>
            <h1>Content without body tag</h1>
            <p>This should still be converted.</p>
        </div>
        """

        markdown_with_frontmatter = html_to_markdown_with_frontmatter(html_content)

        # Check that content is still converted
        self.assertIn("Content without body tag", markdown_with_frontmatter)
        self.assertIn("This should still be converted", markdown_with_frontmatter)

    def test_removes_triple_dashes_from_content(self):
        """Test that --- at the start or end of markdown content is removed."""
        # Test with --- at the beginning
        html_content_start = """
        <html lang="en">
        <body>
            <p>---</p>
            <p>Regular content here</p>
        </body>
        </html>
        """

        markdown_start = html_to_markdown_with_frontmatter(html_content_start)
        lines = markdown_start.split("\n")

        # Check that we have FrontMatter
        self.assertEqual(lines[0], "---")
        # Check that the content doesn't start with --- after the FrontMatter ends
        frontmatter_end = next(i for i in range(1, len(lines)) if lines[i] == "---")
        content_after_frontmatter = "\n".join(lines[frontmatter_end + 1 :])
        self.assertFalse(content_after_frontmatter.strip().startswith("---"))

        # Test with --- at the end
        html_content_end = """
        <html lang="en">
        <body>
            <p>Regular content here</p>
            <p>---</p>
        </body>
        </html>
        """

        markdown_end = html_to_markdown_with_frontmatter(html_content_end)
        # Check that content doesn't end with ---
        self.assertFalse(markdown_end.rstrip().endswith("---\n---"))

        # Test with --- at both beginning and end
        html_content_both = """
        <html lang="en">
        <body>
            <p>---</p>
            <p>Middle content</p>
            <p>---</p>
        </body>
        </html>
        """

        markdown_both = html_to_markdown_with_frontmatter(html_content_both)
        lines_both = markdown_both.split("\n")
        frontmatter_end_both = next(i for i in range(1, len(lines_both)) if lines_both[i] == "---")
        content_both = "\n".join(lines_both[frontmatter_end_both + 1 :])

        # Content should not start or end with ---
        self.assertFalse(content_both.strip().startswith("---"))
        self.assertFalse(content_both.strip().endswith("---"))
        # But should contain "Middle content"
        self.assertIn("Middle content", content_both)


class TestSuperscriptSubscriptConversion(unittest.TestCase):
    """Test superscript and subscript conversion to Unicode in html_to_markdown_with_frontmatter"""

    def test_basic_superscripts(self):
        """Test basic superscript conversion"""
        html = """
        <html>
        <body>
            <p>x<sup>2</sup> + y<sup>3</sup> = z<sup>4</sup></p>
            <p>10<sup>9</sup> is a billion</p>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Check that superscripts are converted to Unicode
        self.assertIn("x²", result)
        self.assertIn("y³", result)
        self.assertIn("z⁴", result)
        self.assertIn("10⁹", result)

        # Should not contain HTML sup tags in markdown
        self.assertNotIn("<sup>", result)
        self.assertNotIn("</sup>", result)

    def test_basic_subscripts(self):
        """Test basic subscript conversion"""
        html = """
        <html>
        <body>
            <p>H<sub>2</sub>O is water</p>
            <p>CO<sub>2</sub> is carbon dioxide</p>
            <p>X<sub>n</sub> represents the nth element</p>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Check that subscripts are converted to Unicode
        self.assertIn("H₂O", result)
        self.assertIn("CO₂", result)
        self.assertIn("Xₙ", result)

        # Should not contain HTML sub tags in markdown
        self.assertNotIn("<sub>", result)
        self.assertNotIn("</sub>", result)

    def test_mixed_super_and_subscripts(self):
        """Test mixed superscripts and subscripts"""
        html = """
        <html>
        <body>
            <p>The formula is x<sup>2</sup> + H<sub>2</sub>O<sup>+</sup></p>
            <p>Chemical: Ca<sup>2+</sup> and SO<sub>4</sub><sup>2-</sup></p>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Check mixed conversions
        self.assertIn("x²", result)
        self.assertIn("H₂O⁺", result)
        self.assertIn("Ca²⁺", result)
        self.assertIn("SO₄²⁻", result)

    def test_special_characters(self):
        """Test special character conversions"""
        html = """
        <html>
        <body>
            <p>Math: (x+y)<sup>n</sup> and f<sub>(x)</sub></p>
            <p>Ion: OH<sup>-</sup> and H<sup>+</sup></p>
            <p>Index: a<sub>i</sub> and b<sup>i</sup></p>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Check special character conversions
        self.assertIn("(x+y)ⁿ", result)
        self.assertIn("f₍ₓ₎", result)
        self.assertIn("OH⁻", result)
        self.assertIn("H⁺", result)
        # subscript i might not be in map, so check either form
        self.assertTrue("aᵢ" in result or "a<sub>i</sub>" in result or "ai" in result)
        self.assertIn("bⁱ", result)

    def test_in_table(self):
        """Test superscripts/subscripts within HTML tables"""
        html = """
        <html>
        <body>
            <table>
                <tr>
                    <th>Chemical</th>
                    <th>Formula</th>
                </tr>
                <tr>
                    <td>Water</td>
                    <td>H<sub>2</sub>O</td>
                </tr>
                <tr>
                    <td>Sulfate ion</td>
                    <td>SO<sub>4</sub><sup>2-</sup></td>
                </tr>
            </table>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Tables should be preserved as HTML but superscripts/subscripts should still be converted
        self.assertIn("<table>", result)

        # Check if conversions happened in table cells
        self.assertTrue("H₂O" in result or "<sub>2</sub>" in result)
        self.assertTrue("SO₄²⁻" in result or "<sub>4</sub><sup>2-</sup>" in result)

    def test_nested_elements(self):
        """Test superscripts/subscripts in nested HTML elements"""
        html = """
        <html>
        <body>
            <div>
                <p>In physics: E = mc<sup>2</sup></p>
                <ul>
                    <li>First: x<sup>1</sup></li>
                    <li>Second: x<sub>2</sub></li>
                </ul>
            </div>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Check conversions in nested structures
        self.assertIn("mc²", result)
        self.assertTrue("x¹" in result or "x1" in result)
        self.assertTrue("x₂" in result or "x2" in result)

    def test_frontmatter_preserved(self):
        """Test that frontmatter is still generated correctly"""
        html = """
        <html lang="es">
        <body>
            <p>Test with x<sup>2</sup></p>
            <table><tr><td>Data</td></tr></table>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Check frontmatter exists
        self.assertTrue(result.startswith("---"))
        self.assertIn("primary_language: es", result)
        self.assertIn("is_table:", result)

        # Also check the conversion happened
        self.assertIn("x²", result)

    def test_unmapped_characters(self):
        """Test characters not in the mapping"""
        html = """
        <html>
        <body>
            <p>Unknown: x<sup>abc</sup> and y<sub>xyz</sub></p>
            <p>Mixed: H<sub>2</sub>SO<sub>4</sub> with note<sup>*</sup></p>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Unmapped characters should be left as-is or handled gracefully
        self.assertIn("H₂SO₄", result)
        # Asterisk is not in the map, so it might remain as-is
        self.assertTrue("note*" in result or "note<sup>*</sup>" in result or "note^*" in result)

    def test_empty_super_subscripts(self):
        """Test empty sup/sub tags"""
        html = """
        <html>
        <body>
            <p>Empty tags: x<sup></sup> and y<sub></sub></p>
            <p>Normal: z<sup>2</sup></p>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Empty tags should not cause errors
        self.assertIn("z²", result)
        # Empty tags should just be removed
        self.assertIn("x", result)
        self.assertIn("y", result)

    def test_complex_math_expression(self):
        """Test a complex mathematical expression"""
        html = """
        <html>
        <body>
            <p>The equation: (x<sub>1</sub>)<sup>2</sup> + (x<sub>2</sub>)<sup>2</sup> = r<sup>2</sup></p>
            <p>Series: a<sub>0</sub> + a<sub>1</sub>x + a<sub>2</sub>x<sup>2</sup> + ... + a<sub>n</sub>x<sup>n</sup></p>
        </body>
        </html>
        """
        result = html_to_markdown_with_frontmatter(html)

        # Check complex nested expressions
        self.assertIn("x₁", result)
        self.assertIn("x₂", result)
        self.assertIn("r²", result)
        self.assertIn("a₀", result)
        self.assertIn("a₁", result)
        self.assertIn("a₂", result)
        self.assertIn("aₙ", result)
        self.assertIn("xⁿ", result)


if __name__ == "__main__":
    unittest.main()
