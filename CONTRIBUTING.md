# Contribuindo

Obrigado por contribuir! Para manter a qualidade:

1. Faça fork, crie um branch e instale o projeto em modo editável:
   `pip install -e . pytest pytest-cov hypothesis ruff mypy`.
2. **Nunca** invente posições de campos ou regras. Toda alteração de leiaute
   deve vir de uma fonte oficial citada em `scripts/generate_layouts.py`.
3. Todo bugfix precisa de um teste que falhe antes da correção.
4. Antes de abrir o PR, rode:

   ```bash
   ruff check .
   ruff format --check .
   mypy
   python -m pytest
   ```

5. Cobertura mínima: 95%. Testes não devem ser removidos ou enfraquecidos para
   passar.
6. Commits seguem Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`…).

Não publique pacotes, não faça `git push` e não toque em arquivos fora deste
repositório.
