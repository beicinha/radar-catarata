"""Testes sem rede das fontes acrescentadas em 08/11/2026."""
import unittest
from unittest.mock import patch

import avisar
import coletor
import diarios_municipais as dm
import informes
import mapeamento

CARD = '''<p>Mostrando <strong>1</strong> a <strong>1</strong> de <strong>1</strong> matérias.</p>
<ul class="lista-materias"><li class="materia-card">
 <h2 class="materia-card__titulo"><a href="/amm-mg/materia/ABC123" target="_blank">AVISO DE CREDENCIAMENTO Nº 5/2026</a></h2>
 <p class="materia-card__origem"><span class="materia-card__entidade">Prefeitura Municipal de Exemplo</span>
 <span class="materia-card__orgao">SAÚDE</span></p>
 <p class="materia-card__trecho">credenciamento de clínicas para cirurgia de <mark>catarata</mark></p>
 <dl><div><dt>Circulação</dt><dd>05/11/2026</dd></div></dl>
</li></ul>'''


class DiariosAssociacoes(unittest.TestCase):
    def test_le_cartao_da_busca(self):
        cards, total = dm.ler_busca(CARD, "amm-mg")
        self.assertEqual(total, 1)
        self.assertEqual(cards[0]["codigo"], "ABC123")
        self.assertEqual(cards[0]["data"], "2026-11-05")
        self.assertEqual(cards[0]["entidade"], "Prefeitura Municipal de Exemplo")
        self.assertIn("catarata", cards[0]["trecho"])

    def test_municipio(self):
        self.assertEqual(dm.municipio_de("Prefeitura de Guaxupé"), "Guaxupé")
        self.assertEqual(dm.municipio_de("Prefeitura Municipal de Cafelândia"), "Cafelândia")
        self.assertEqual(dm.municipio_de("CISCEM - CONSÓRCIO INTERMUNICIPAL DE SAÚDE"), "")

    def test_classificacao(self):
        m = lambda titulo: {"titulo": titulo, "trecho": ""}
        aviso = ("O Município torna público que realizará credenciamento de pessoas jurídicas para "
                 "prestação de serviços de cirurgia de catarata por facoemulsificação.")
        self.assertEqual(dm.classificar(m("AVISO DE CREDENCIAMENTO Nº 1/2026"), aviso), "oportunidade")
        extrato = "Contratada: Clínica X. Objeto: prestação de serviços de cirurgia de catarata com LIO."
        self.assertEqual(dm.classificar(m("EXTRATO DE CONTRATO Nº 10/2026"), extrato), "mapa")
        self.assertIsNone(dm.classificar(m("PORTARIA Nº 9/2026"), aviso))
        self.assertIsNone(dm.classificar(m("AVISO DE TORNAR SEM EFEITO - EDITAL DE CREDENCIAMENTO"), aviso))
        self.assertIsNone(dm.classificar(m("AVISO DE LICITAÇÃO"), "Passeio turístico às Cataratas do Iguaçu"))


class Mapeamento(unittest.TestCase):
    def test_contrato_assinado_nao_gera_alerta(self):
        item = {"fonte": "Mapeamento", "categoria": "Catarata",
                "objeto": "Credenciamento para prestação de serviços de cirurgia de catarata"}
        self.assertFalse(avisar.relevante(item))

    def test_coleta_contratos_com_fornecedor_e_sem_compras(self):
        busca = {"items": [
            {"item_url": "/contratos/111/2026/5", "description": "Prestação de serviços de cirurgia de catarata com LIO",
             "data_publicacao_pncp": "2026-10-01T10:00:00", "data_fim_vigencia": "2027-01-31", "uf": "MG",
             "municipio_nome": "Exemplo", "orgao_nome": "Município de Exemplo", "codigo_ibge": "",
             "modalidade_licitacao_nome": "Credenciamento", "valor_global": 1000.0},
            {"item_url": "/contratos/111/2026/6", "description": "Aquisição de lentes intraoculares para catarata",
             "data_publicacao_pncp": "2026-10-01T10:00:00", "data_fim_vigencia": "2027-01-31"}]}

        def cjson(url, default=None):
            if "/api/search/" in url:
                return busca if "q=catarata" in url and "contrato" in url else {"items": []}
            return {"nomeRazaoSocialFornecedor": "Clínica Exemplo Ltda", "niFornecedor": "00",
                    "valorGlobal": 2000.0, "dataVigenciaFim": "2027-02-28"}

        with patch.object(mapeamento.time, "sleep"):
            itens, status = mapeamento.coletar(cjson, {}, "2026-11-08", lambda ib: None, {})
        self.assertTrue(status["ok"])
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["vencedores"], ["Clínica Exemplo Ltda"])
        self.assertEqual(itens[0]["vigencia_fim"], "2027-02-28")
        self.assertTrue(itens[0]["credenciamento_aberto"])
        self.assertEqual(itens[0]["encerramento"], "")

    def test_informe_contrato_vencendo(self):
        dados = {"atualizado": "2026-11-08 10:00", "itens": [
            {"fonte": "Mapeamento", "categoria": "Catarata", "vigencia_fim": "2026-12-31", "orgao": "Órgão X",
             "municipio": "Exemplo", "uf": "MG", "vencedores": ["Clínica Y"], "link": "https://pncp.gov.br/x"}]}
        texto = informes.detalhe("vencendo", dados, [], 0)
        self.assertIn("Clínica Y", texto)
        self.assertIn("31/12/2026", texto)
        self.assertIn("não é edital aberto", texto)


class PncpGenericos(unittest.TestCase):
    def test_edital_generico_conferido_pelos_itens(self):
        it = {"item_url": "/compras/123/2026/7"}
        itens = [{"descricao": "Cirurgia de catarata por facoemulsificação"}, {"descricao": "Colecistectomia"}]
        with patch.object(coletor, "cjson", return_value=itens), patch.object(coletor.time, "sleep"):
            cache = {}
            self.assertIn("catarata", coletor.itens_oftalmo(it, cache))
        with patch.object(coletor, "cjson", side_effect=AssertionError("não deve reconsultar no mesmo dia")):
            self.assertIn("catarata", coletor.itens_oftalmo(it, cache))


if __name__ == "__main__":
    unittest.main()
