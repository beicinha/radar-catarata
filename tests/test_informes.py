import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import avisar
import informes


class Conteudo(unittest.TestCase):
    def setUp(self):
        self.dados = {'atualizado': '2026-11-07 18:27', 'concluido': '2026-11-07 18:34',
                      'rodada': '100', 'fontes_status': [{'nome': 'PNCP', 'ok': True}]}
        self.repertorio = [{'tipo': 'resumo', 'titulo': 'Resumo'}]

    def criar(self, resultado='success', rodada='100'):
        return informes.criar(self.dados, [], self.repertorio, 0, resultado, rodada,
                              avisar.AGORA, 'https://example.org/painel')[0]

    def test_procura_concluida_exige_identificador_da_rodada(self):
        self.assertIn('Procura concluída nas fontes configuradas.', self.criar())
        self.assertIn('18:34', self.criar())
        self.assertIn('Sem confirmação de nova procura', self.criar(rodada='outra'))

    def test_procura_parcial_nao_afirma_ausencia_de_novidades(self):
        self.dados['fontes_status'].append({'nome': 'Diário', 'ok': False})
        texto = self.criar()
        self.assertIn('Procura parcial concluída.', texto)
        self.assertIn('Não é possível concluir ausência de novidades', texto)
        self.assertIn('1/2', texto)

    def test_falha_ou_etapa_pulada_nao_afirma_procura_feita(self):
        self.assertIn('procura desta rodada falhou', self.criar(resultado='failure'))
        self.assertIn('não foi executada', self.criar(resultado='skipped'))

    def test_repertorio_usa_fontes_e_rotula_lembretes(self):
        p = Path(avisar.__file__).parent/'repertorio_informes.json'
        catalogo = json.loads(p.read_text())
        item = {'municipio': 'Município de exemplo', 'uf': 'SP', 'categoria': 'Catarata',
                'encerramento': '2026-12-31', 'dist_km': 100, 'fonte': 'PNCP',
                'link': 'https://example.org/edital',
                'req': {'status': 'ok', 'oferece': [{'r': 'Órgão cede o centro cirúrgico/hospital'}]}}
        for i, tema in enumerate(catalogo):
            texto, tipo = informes.criar(self.dados, [item], catalogo, i, 'success', '100', avisar.AGORA, 'painel')
            self.assertEqual(tipo, tema['tipo'])
            if tipo in ('prazo', 'perto', 'retomar', 'estrutura'):
                self.assertIn('não é novidade', texto)
                self.assertIn(item['link'], texto)


class Envios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        (self.p/'dados.json').write_text(json.dumps({'atualizado': '2026-11-07 18:27',
              'concluido': '2026-11-07 18:34', 'rodada': '100', 'itens': [],
              'fontes_status': [{'nome': 'PNCP', 'ok': True}]}))
        for p in (patch.object(avisar, 'AQUI', self.tmp.name),
                  patch.object(avisar.sys, 'argv', ['avisar.py', '--informe']),
                  patch.dict(os.environ, {'GITHUB_RUN_ID': '100', 'COLETA_RESULTADO': 'success'})):
            p.start()
            self.addCleanup(p.stop)

    def rodar(self):
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                avisar.main()
            except SystemExit as e:
                if e.code != 1:
                    raise

    def test_sem_novidade_envia_um_informe_por_canal_e_nao_duplica_rodada(self):
        with patch.object(avisar, 'enviar_email', return_value=True) as email, \
                patch.object(avisar, 'enviar_whatsapp', return_value='aceito_sem_confirmacao') as zap:
            self.rodar()
            self.rodar()
            email.assert_called_once()
            zap.assert_called_once()
            self.assertIn('Sem novos avisos pendentes', email.call_args.args[1])
            self.assertIn('Procura concluída', zap.call_args.args[0])
        self.assertEqual(json.loads((self.p/'avisados.json').read_text()), {})

    def test_nova_rodada_alterna_tema_sem_repetir_alertas(self):
        with patch.object(avisar, 'enviar_email', return_value=True), \
                patch.object(avisar, 'enviar_whatsapp', return_value='aceito_sem_confirmacao'):
            self.rodar()
            with patch.dict(os.environ, {'GITHUB_RUN_ID': '101'}):
                self.rodar()
        h = json.loads((self.p/'informes.json').read_text())
        self.assertNotEqual(h['rodadas']['100']['tema'], h['rodadas']['101']['tema'])

    def test_falha_email_nao_repete_whatsapp_da_mesma_rodada(self):
        with patch.object(avisar, 'enviar_email', side_effect=[False, True]) as email, \
                patch.object(avisar, 'enviar_whatsapp', return_value='aceito_sem_confirmacao') as zap:
            self.rodar()
            self.rodar()
            self.assertEqual(email.call_count, 2)
            zap.assert_called_once()

    def test_simulacao_do_informe_nao_envia_nem_grava(self):
        with patch.object(avisar.sys, 'argv', ['avisar.py', '--informe', '--teste']), \
                patch.object(avisar, 'enviar_email') as email, patch.object(avisar, 'enviar_whatsapp') as zap:
            self.rodar()
            email.assert_not_called()
            zap.assert_not_called()
        self.assertFalse((self.p/'informes.json').exists())
        self.assertFalse((self.p/'avisados.json').exists())


if __name__ == '__main__':
    unittest.main()
