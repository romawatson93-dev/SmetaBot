SELECT c.id, c.title, c.contractor_id, c.tg_chat_id, COUNT(p.id) AS count FROM core.channels c LEFT JOIN core.publications p ON p.channel_id = c.id GROUP BY c.id ORDER BY c.id;
