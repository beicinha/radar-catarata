import unittest

import plataformas

LISTA = '''<tbody id="tableProcessDataBody">
<tr>
  <td class="tablebutton"><a class="btn" href="/Process/ProcessView?param1=%5Bgkz%5Dabc%3D" target="_blank"><i></i></a></td>
  <td class="orgnamewidth">MUNICIPIO DE NOVA GRANADA</td>
  <td>06/2026</td>
  <td>CREDENCIAMENTO</td>
  <td>NOVA GRANADA-SP</td>
  <td>RECEP&#199;&#195;O DE PROPOSTAS</td>
  <td>06/11/2026 17:37</td>
  <td>05/01/2027 09:00</td>
</tr>
</tbody>'''

PROCESSO = '''<input id="TotalBaseValue" name="TotalBaseValue" type="text" value="R$ 1.871.213,5100" />
<textarea id="ProductOrService" name="ProductOrService">
Credenciamento de empresas para realiza&#231;&#227;o de cirurgias de catarata por facoemulsifica&#231;&#227;o</textarea>'''


class Plataformas(unittest.TestCase):
    def test_le_lista_publica_e_processo(self):
        linhas = plataformas.ler_lista(LISTA, "https://bllcompras.com")
        self.assertEqual(len(linhas), 1)
        ln = linhas[0]
        self.assertEqual((ln["cidade"], ln["uf"], ln["numero"]), ("NOVA GRANADA", "SP", "06/2026"))
        self.assertEqual(ln["status"], "RECEPÇÃO DE PROPOSTAS")
        self.assertEqual(ln["disputa"], "2027-01-05T09:00")
        self.assertTrue(ln["link"].startswith("https://bllcompras.com/Process/ProcessView?param1="))
        objeto, valor = plataformas.ler_processo(PROCESSO)
        self.assertIn("catarata", objeto)
        self.assertEqual(valor, 1871213.51)

    def test_lista_sem_tabela_e_falha_da_fonte(self):
        with self.assertRaises(RuntimeError):
            plataformas.ler_lista("<html>captcha</html>", "https://bllcompras.com")

    def test_item_da_lista_sai_quando_encerra_ou_finaliza(self):
        base = {"objeto": "Credenciamento para cirurgias de catarata", "uf": "SP", "cidade": "NOVA GRANADA",
                "status": "RECEPÇÃO DE PROPOSTAS", "disputa": "2026-12-01T09:00", "plataforma": "BLL Compras",
                "primeira_vez": "2026-11-08"}
        cache = {"lista:a": dict(base), "lista:b": dict(base, disputa="2026-11-01T09:00"),
                 "lista:c": dict(base, status="HOMOLOGADO"), "lista:d": dict(base, objeto="Obra de pavimentação")}
        itens = plataformas.itens_lista(cache, "2026-11-08", {}, lambda ib: None)
        self.assertEqual([i["id"] for i in itens], ["priv:lista:a"])
        self.assertEqual(itens[0]["fonte"], "Plataforma privada")
        self.assertEqual(itens[0]["categoria"], "Catarata")

    def test_nao_duplica_o_que_ja_esta_no_pncp(self):
        pncp = [{"id": "pncp:1/2026/5", "uf": "PI", "municipio": "União"},
                {"id": "pncp:2/2026/9", "uf": "SP", "municipio": "Nova Granada"}]
        cache_pncp = {"1/2026/5": {"consulta": {"linkSistemaOrigem":
                      "https://www.portaldecompraspublicas.com.br/processos/PI/X-2372/PE-66-2026-2026-518964"}},
                      "2/2026/9": {"consulta": {"numeroCompra": "006", "anoCompra": 2026}}}
        codigos, numeros = plataformas.chaves_pncp(pncp, cache_pncp)
        cache = {"pcp:518964": {}, "pcp:1": {"num": ["7", "2026"], "local": ["SP", "nova granada"]},
                 "lista:x": {"num": ["6", "2026"], "local": ["SP", "nova granada"]}}
        itens = [{"id": "priv:pcp:518964"}, {"id": "priv:pcp:1"}, {"id": "priv:lista:x"}]
        self.assertEqual([i["id"] for i in plataformas.sem_duplicar(itens, cache, codigos, numeros)], ["priv:pcp:1"])

    def test_pcp_filtra_finalizados_vencidos_e_compras(self):
        def r(cod, resumo, status="Recebendo Propostas", fim="2026-12-01T12:00:00Z"):
            return {"codigoLicitacao": cod, "resumo": resumo, "numero": "1/2026",
                    "statusProcessoPublico": {"descricao": status}, "dataHoraFinalPropostas": fim,
                    "dataHoraPublicacao": "2026-11-01T10:00:00Z", "urlReferencia": f"/sp/x/cred-{cod}",
                    "tipoLicitacao": {"tipoLicitacao": "Credenciamento"},
                    "unidadeCompradora": {"cidade": "Monte Alto", "uf": "SP", "nomeUnidadeCompradora": "Pref"}}
        resp = {"result": [r(1, "Credenciamento para cirurgias de catarata"),
                           r(2, "Credenciamento para cirurgias de catarata", status="Processo Finalizado"),
                           r(3, "Credenciamento para cirurgias de catarata", fim="2026-10-01T12:00:00Z"),
                           r(4, "Aquisição de caixas cirúrgicas para catarata")], "pageCount": 1}
        cache = {}
        itens = plataformas.coletar_pcp(lambda u: resp, cache, "2026-11-08", {}, lambda ib: None, pausa=0)
        self.assertEqual([i["id"] for i in itens], ["priv:pcp:1"])
        self.assertTrue(itens[0]["link"].startswith("https://www.portaldecompraspublicas.com.br/processos/sp/"))
        self.assertEqual(itens[0]["plataforma_nome"], "Portal de Compras Públicas")


if __name__ == "__main__":
    unittest.main()
