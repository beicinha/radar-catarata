import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import timedelta

import analise_editais
import avisar
import coletor
import regras


class Filtros(unittest.TestCase):
    def test_compras_e_turismo_nao_sao_cirurgia(self):
        for objeto in (
            'CONTRATAÇÃO PARA O FORNECIMENTO PARCELADO DE CAIXAS CIRÚRGICAS PARA PROCEDIMENTOS DE CIRURGIA DE CATARATA',
            'Kit de vitrectomia e para facoemulsificação, lentes intraoculares',
        ):
            self.assertEqual(regras.classificar(objeto), 'Material/compra')
            self.assertFalse(avisar.relevante({'categoria': 'Catarata', 'objeto': objeto}))
        self.assertIsNone(regras.classificar('Passeio turístico às Cataratas do Iguaçu'))

    def test_servico_com_insumos_continua_relevante(self):
        objeto = 'Credenciamento para prestação de serviços de cirurgia de catarata com fornecimento de lentes, insumos e equipamentos'
        self.assertEqual(regras.classificar(objeto), 'Catarata')
        self.assertTrue(avisar.relevante({'categoria': 'Catarata', 'objeto': objeto}))

    def test_credenciamento_com_prestadores_deve_ser_conferido(self):
        self.assertTrue(avisar.relevante({'objeto': 'Credenciamento de cirurgia de catarata', 'vencedores': ['Prestador']}))
        self.assertFalse(avisar.relevante({'objeto': 'Contratação para realização de cirurgias de catarata', 'vencedores': ['Prestador']}))

    def test_diario_administrativo_e_resultados(self):
        for objeto in ('SEMSA Arquivos diversos 2019. Auditoria catarata CX 509 2018. Processo de licitação.',
                       'Extrato de contrato de cirurgia de catarata, termo aditivo'):
            self.assertFalse(regras.diario_contratacao(objeto))
        self.assertTrue(regras.diario_contratacao('Aviso de licitação para prestação de serviços de cirurgia de catarata'))

    def test_preco_de_material_nao_e_valor_cirurgico(self):
        for desc in ('Kit para cirurgia de catarata', 'Blefarostato para cirurgia de catarata', 'Passeio turístico às Cataratas'):
            self.assertFalse(regras.valor_cirurgia({'descricao': desc}))
        self.assertTrue(regras.valor_cirurgia({'descricao': 'Facoemulsificação com implante de LIO e insumos inclusos'}))

    def test_consultas_multiespecialidades_e_locacao_nao_disparam(self):
        for objeto in ('Credenciamento de consultas em cirurgia geral, cirurgia vascular e oftalmologia',
                       'Locação de microscópio cirúrgico oftalmológico com manutenção integral'):
            self.assertFalse(avisar.relevante({'objeto': objeto}))

    def test_prazo_hora_encerrada(self):
        item = {'objeto': 'Credenciamento de cirurgia de catarata',
                'encerramento': (avisar.AGORA - timedelta(minutes=1)).isoformat()}
        self.assertFalse(avisar.relevante(item))

    def test_negacoes_e_equipamento_do_municipio(self):
        for texto in ('A vistoria não será obrigatória.', 'Não será exigido atestado de capacidade técnica.',
                      'O município disponibilizará equipamentos, incluindo facoemulsificador e microscópio cirúrgico.'):
            self.assertEqual(analise_editais.analisar_texto(texto)['exige'], [])
        self.assertTrue(analise_editais.analisar_texto('Será exigido atestado de capacidade técnica.')['exige'])

    def test_fonte_inacessivel_nao_vira_zero_resultados(self):
        with patch.object(coletor, 'load', side_effect=lambda f, d: [{'nome': 'Fonte', 'url': 'https://example.org'}] if f == 'fontes_oss.json' else {}), \
                patch.object(coletor, 'curl', side_effect=RuntimeError('indisponível')):
            itens, status = coletor.coletar_oss({})
        self.assertFalse(status[0]['ok'])


class Avisos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.item = {'id': 'teste', 'objeto': 'Credenciamento de cirurgia de catarata',
                     'categoria': 'Catarata', 'primeira_vez': '2020-01-01'}
        self.escrever([self.item])
        self.patches = [patch.object(avisar, 'AQUI', self.tmp.name),
                        patch.object(avisar.sys, 'argv', ['avisar.py'])]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def escrever(self, itens):
        (self.p / 'dados.json').write_text(json.dumps({'itens': itens}))

    def rodar(self):
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                avisar.main()
            except SystemExit as erro:
                if erro.code != 1:
                    raise

    def test_recupera_whatsapp_sem_repetir_email(self):
        with patch.object(avisar, 'enviar_email', return_value=True) as email, \
                patch.object(avisar, 'enviar_whatsapp', side_effect=['falha_conexao', 'aceito_sem_confirmacao']) as zap:
            self.rodar()
            self.rodar()
            self.assertEqual(email.call_count, 1)
            self.assertEqual(zap.call_count, 2)

    def test_excecao_email_nao_impede_whatsapp(self):
        with patch.object(avisar, 'enviar_email', side_effect=RuntimeError('SMTP')), \
                patch.object(avisar, 'enviar_whatsapp', return_value='aceito_sem_confirmacao') as zap:
            self.rodar()
            zap.assert_called_once()

    def test_aceito_nao_significa_entregue_nem_repete_na_mesma_rodada(self):
        with patch.object(avisar, 'enviar_email', return_value=True), \
                patch.object(avisar, 'enviar_whatsapp', return_value='aceito_sem_confirmacao') as zap:
            self.rodar()
            self.rodar()
            self.assertEqual(zap.call_count, 1)
        estado = json.loads((self.p/'avisados.json').read_text())['teste']['whatsapp']
        self.assertEqual(estado['status'], 'aceito_sem_confirmacao')

    def test_legado_preserva_email_e_recupera_whatsapp(self):
        (self.p/'avisados.json').write_text(json.dumps({'teste': '2026-11-07'}))
        with patch.object(avisar, 'enviar_email') as email, \
                patch.object(avisar, 'enviar_whatsapp', return_value='aceito_sem_confirmacao') as zap:
            self.rodar()
            email.assert_not_called()
            zap.assert_called_once()

    def test_simulacao_nao_envia_nem_grava(self):
        with patch.object(avisar.sys, 'argv', ['avisar.py', '--teste']), \
                patch.object(avisar, 'enviar_email') as email, patch.object(avisar, 'enviar_whatsapp') as zap:
            self.rodar()
            email.assert_not_called()
            zap.assert_not_called()
        self.assertFalse((self.p/'avisados.json').exists())
        self.assertFalse((self.p/'status_avisos.json').exists())

    def test_historico_corrompido_nao_reenvia_tudo(self):
        (self.p/'avisados.json').write_text('inválido')
        with self.assertRaises(ValueError), patch.object(avisar, 'enviar_email') as email:
            self.rodar()
        email.assert_not_called()

    def test_lote_so_marca_itens_realmente_incluidos(self):
        self.escrever([dict(self.item, id=str(n)) for n in range(20)])
        with patch.object(avisar, 'enviar_email', return_value=True), \
                patch.object(avisar, 'enviar_whatsapp', return_value='aceito_sem_confirmacao'):
            self.rodar()
        h = json.loads((self.p/'avisados.json').read_text())
        self.assertEqual(sum('email' in i for i in h.values()), 15)
        self.assertEqual(sum('whatsapp' in i for i in h.values()), 5)

    def test_teste_whatsapp_simulado_nao_envia(self):
        with patch.object(avisar.sys, 'argv', ['avisar.py', '--teste-whatsapp', '--teste']), \
                patch.object(avisar, 'enviar_whatsapp') as zap:
            self.rodar()
            zap.assert_not_called()
        self.assertFalse((self.p/'avisados.json').exists())

    def test_fila_sem_confirmacao_tem_limite_e_intervalo(self):
        agora = avisar.AGORA
        h = {'whatsapp': {'status': 'aceito_sem_confirmacao', 'aceitas': 1,
                          'ultima_tentativa': (agora - timedelta(hours=25)).isoformat()}}
        self.assertTrue(avisar.pendente(h, 'whatsapp'))
        h['whatsapp']['ultima_tentativa'] = agora.isoformat()
        self.assertFalse(avisar.pendente(h, 'whatsapp'))
        h['whatsapp'].update(aceitas=3, ultima_tentativa=(agora - timedelta(days=2)).isoformat())
        self.assertFalse(avisar.pendente(h, 'whatsapp'))

    def test_resposta_callmebot_negativa_nao_e_sucesso(self):
        for resposta in ('Message not sent', 'Error: invalid API key', 'Your message was not sent, queued requests failed'):
            self.assertNotEqual(avisar.interpretar_whatsapp(resposta), 'aceito_sem_confirmacao')
        self.assertEqual(avisar.interpretar_whatsapp('Message queued. You will receive it soon.'), 'aceito_sem_confirmacao')
        self.assertEqual(avisar.interpretar_whatsapp('Message sent successfully'), 'aceito_sem_confirmacao')
        self.assertEqual(avisar.interpretar_whatsapp('Unexpected page'), 'resposta_desconhecida')


if __name__ == '__main__':
    unittest.main()
