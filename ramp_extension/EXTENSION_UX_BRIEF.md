# Extension Popup UX — Brief for Product/UX Review

## Context

Chrome extension popup (360×520px) for a Reddit content executor.

**User:** Женя (и будущие executor'ы) — человек который постит комментарии/посты в Reddit от имени аватаров. Не технический. Работает 1-2 сессии в день по 15-30 мин.

**Flow:** Система генерирует задачи (EPG slots) → executor видит их в popup → approve → extension автоматически постит в нужное время. Либо executor постит вручную по email-инструкции.

**Каналы доставки:** Extension (автоматически) или Email (ручная работа executor'a).

---

## Текущее состояние

Popup показывает:
- Header: аккаунт + статус подключения
- "Needs Approval" — задачи ожидающие одобрения
- "Today's Schedule" — статистика (Plan / Posted / Waiting / Missed) + список запланированных
- "Done" — выполненные
- "Failed" — неудачные

Каждая карточка задачи содержит: subreddit, thread title, время, текст комментария, кнопки действий.

---

## Вопросы к аналитику

### 1. Информационная архитектура карточки

Какие поля в карточке задачи реально нужны executor'у для принятия решения "approve / skip / edit"?

Варианты полей:
- **Subreddit** (r/whoop)
- **Thread title** (кликабельная ссылка на тред)
- **Deadline** (by 10:25 — мягкое окно)
- **Comment text preview** (первые 100 символов)
- **Source** (EPG / manual) — нужно ли executor'у знать откуда задача?
- **Type** (comment / post) — нужно ли различать визуально?
- **Avatar** (u/username) — если executor работает с несколькими аватарами

Что из этого шум, а что критично для решения?

### 2. Приоритет секций

Правильный ли порядок сверху вниз?

```
[Status bar]
[Needs Approval]  ← действие требуется
[Today's Schedule] ← информация
[Done]             ← архив
[Failed]           ← ошибки
```

Или executor'у важнее видеть что-то другое первым?

### 3. Статистика (Plan / Posted / Waiting / Missed)

- Нужны ли эти 4 цифры вообще? Или это "dashboard noise"?
- Executor care-ит сколько осталось (Waiting) или сколько всего (Plan)?
- "Missed" — это демотиватор или полезная обратная связь?

### 4. Soft deadline vs exact time

Мы переходим на модель "окно" вместо "точное время":
- Задача получает окно 2 часа (напр. 08:00-10:00)
- Extension сам выбирает момент внутри окна
- Email показывает "Post by 10:00"

**Вопрос:** как показать окно в popup?
- `by 10:25` (только deadline)
- `08:25 — 10:25` (полное окно)
- Вообще не показывать время (extension всё делает сам, executor'у не важно)
- Показывать только если что-то overdue/urgent

### 5. Empty state

Когда задач нет — что показать?
- "Nothing to approve — you're all set 👍" (текущее)
- Следующее запланированное действие ("Next task at ~14:00")
- Общий статус дня ("3 tasks scheduled for today, all auto-posting")
- Мотивационное ("Yesterday: 5 posted, avg karma +3")

### 6. Действия с карточкой

Текущий набор кнопок:
- ✓ Approve
- ✎ Edit (раскрывает textarea)
- ✗ Skip

Достаточно? Слишком много? Нужно ли:
- "Delay" (отложить на час)?
- "Open thread" (посмотреть тред перед approve)?
- Drag-to-reorder (изменить порядок постинга)?

### 7. Визуальный стиль

- Dark theme (текущий) — подходит? Или executor предпочтёт light?
- 360px ширина — достаточно для текста комментария?
- Нужны ли цветовые индикаторы (green=done, red=failed) или текст достаточен?

### 8. Сценарий "утренний батч"

Женя садится утром, видит 5 задач. Её flow:
1. Открыть popup
2. Пролистать все 5
3. "Approve All"
4. Закрыть

**Вопрос:** нужен ли ей вообще просмотр каждой карточки? Или достаточно:
- Число задач + "Approve All" button
- Один конфликт/проблема показать отдельно (locked thread, expired)

### 9. Multi-avatar

Если executor работает с 3 аватарами — нужна ли фильтрация/группировка по аватару?
Или popup всегда привязан к одному (тому что залогинен в Reddit)?

### 10. Нотификации

Нужны ли push notifications (Chrome desktop)?
- Когда новая задача пришла?
- Когда задача failed?
- Или popup badge (число на иконке) достаточно?

---

## Constraints

- Popup: 360×520px max (Chrome limitation)
- Service worker ephemeral (MV3) — нет persistent state
- Extension привязана к одному Reddit аккаунту (тому что залогинен)
- Executor может быть offline — tasks не теряются, ждут в очереди

---

## Текущий скриншот

(см. приложенный скриншот — popup с 1 задачей в Today's Schedule)

Проблемы видимые на скриншоте:
- Строка задачи перегружена: `EPG 💬 🕐 05:16 PM r/whoop → Taking Melatonin...`
- Непонятно что кликабельно
- "Needs Approval" пустая но занимает место
- Статистика 1/0/1/0 непонятна без контекста
