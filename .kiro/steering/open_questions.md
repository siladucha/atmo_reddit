---
inclusion: manual
---

# Open Questions & Future Ideas

Место для идей и вопросов, которые появляются во время работы, но не требуют немедленной реализации. Пересматривается на weekly architecture review.

---

## 2026-07-02: `portal` delivery channel для self-service клиентов

**Контекст:** При добавлении селектора delivery_channel на аватар (email/extension/both) возник вопрос — что если аватар принадлежит клиенту без execution layer?

**Идея:** Четвёртый вариант `portal` — "мы не управляем постингом". ExecutionTask не создаётся, email не шлётся, extension не нужен. Клиент видит approved drafts в портале и постит сам.

**Для кого:**
- Self-service trial клиенты (BYOA)
- Дешёвые планы без managed execution
- Переходный период: клиент начинает сам → потом переключаем на managed

**Что это меняет:**
- `create_execution_task()` при `delivery_channel="portal"` → return None (не создавать задачу)
- Portal review queue показывает approved drafts с кнопкой "I posted this" → submit permalink
- Draft reconciliation подхватывает остальное

**Статус:** Не нужно прямо сейчас. Добавить когда появится реальный self-service клиент с BYOA.

---

## 2026-07-04: A/B тест методов постинга → влияние на аватар

**Контекст:** Extension v3 переходит на old.reddit.com (стабильный DOM). Но нет данных о том, как разные методы постинга влияют на долгосрочное здоровье аватара. Reddit может детектировать programmatic posting по каким-то неизвестным сигналам.

**Эксперимент:**
- Группа A: old.reddit.com (textarea + .save click) — 2-3 аватара
- Группа B: manual posting (email → executor руками) — 2-3 аватара (контроль)
- Группа C: new reddit debugger (chrome.debugger) — 1-2 аватара

**Метрики:** removal rate, karma velocity, shadowban, CQS, subreddit bans

**Гипотеза H0:** Метод постинга не влияет на здоровье аватара (Reddit не детектирует КАК текст вставлен)

**Длительность:** 8 недель, еженедельные отчёты

**Спек:** `.kiro/specs/extension-posting-ab-test/requirements.md`

**Статус:** Requirements ready. Нужен design + implementation.

---
