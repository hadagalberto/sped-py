# Contribuindo

Obrigado por contribuir! Para manter a qualidade:

1. Faça fork, crie um branch e instale o projeto em modo editável:
   `pip install -e . pytest pytest-cov hypothesis ruff mypy`.
2. **Nunca** invente posições de campos ou regras. Toda alteração de leiaute
   deve vir de uma fonte oficial citada em `scripts/generate_layouts.py`.
   Fórmulas de apuração vivem em `sped.validation.totals` com a fonte citada;
   a análise reutiliza essas funções puras — não as copie.
3. Todo bugfix precisa de um teste que falhe antes da correção. Testes devem
   usar vetores sintéticos válidos e inválidos conhecidos; nunca remova ou
   enfraqueça um teste para fazê-lo passar, e nunca use testes pulados.
4. Antes de abrir o PR, rode:

   ```bash
   python -m pip install -e '.[test]' pytest pytest-cov hypothesis ruff mypy
   ruff check .
   ruff format --check .
   mypy
   python -m pytest -m "not slow"
   python -m pytest -m slow   # streaming de 1 GB, antes de publicar uma release
   ```

5. Cobertura mínima: 95%. Novos módulos de análise/exportação precisam de
   testes positivos e negativos; mudanças em `merge`/`split` devem verificar que
   o resultado passa em `sped validate`.
6. Commits seguem Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`…).

Não publique pacotes, não faça `git push` e não toque em arquivos fora deste
repositório.
