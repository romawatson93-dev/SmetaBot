-- Example view for contractor dashboard
CREATE OR REPLACE VIEW v_contractor_rooms AS
SELECT r.*, c.title AS contractor_title
FROM rooms r
JOIN contractors c ON c.id = r.contractor_id;
