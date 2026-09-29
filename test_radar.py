import unittest

import radar


class RadarTests(unittest.TestCase):
    def test_normaliza_acentos(self):
        self.assertEqual(radar.normalize("Açúcar União 1kg"), "acucar uniao 1kg")

    def test_classifica_apenas_com_historico_suficiente_ou_alvo(self):
        product = {"name": "Café", "target_price": 10}
        offer = {"product": "Café", "store": "Loja", "price": 9, "shipping": 0}
        result = radar.classify_offer(offer, product, {}, 3)
        self.assertTrue(result["deal"])
        self.assertEqual(result["deal_label"], "abaixo do preço-alvo")

    def test_listas_nao_adicionam_produtos_ao_radar(self):
        lists = {"Dudu": [{"product_name": "Leite", "quantity": 2}]}
        offers = [{"product": "Leite", "effective_price": 5, "store": "Loja"}]
        result = radar.shopping_suggestions(lists, offers)
        self.assertEqual(result["Dudu"][0]["quantity"], 2)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["product"], "Leite")

    def test_amazon_parser_le_resultado_simples(self):
        parser = radar.AmazonSearchParser()
        parser.feed('<div data-component-type="s-search-result"><h2><a href="/dp/123"><span>Café Pilão 500g</span></a></h2><span class="a-offscreen">R$ 19,90</span></div>')
        self.assertEqual(len(parser.items), 1)
        self.assertEqual(parser.items[0]["title"], "Café Pilão 500g")
        self.assertEqual(parser.items[0]["price"], "R$ 19,90")


if __name__ == "__main__":
    unittest.main()
