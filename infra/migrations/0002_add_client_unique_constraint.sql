-- Добавляем уникальное ограничение для core.clients
-- Это предотвратит дублирование клиентов в одном канале

-- Сначала удаляем возможные дубликаты
DELETE FROM core.clients 
WHERE id NOT IN (
    SELECT MIN(id) 
    FROM core.clients 
    GROUP BY channel_id, tg_user_id
);

-- Добавляем уникальное ограничение
ALTER TABLE core.clients 
ADD CONSTRAINT unique_client_per_channel 
UNIQUE (channel_id, tg_user_id);
