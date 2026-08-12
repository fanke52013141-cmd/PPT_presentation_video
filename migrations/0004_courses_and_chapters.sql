CREATE TABLE IF NOT EXISTS courses (
    id VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    description VARCHAR,
    cover_color VARCHAR NOT NULL DEFAULT '#5B7893',
    cover_image_path VARCHAR,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_courses_id ON courses (id);
CREATE INDEX IF NOT EXISTS ix_courses_sort_order ON courses (sort_order);

CREATE TABLE IF NOT EXISTS chapters (
    id VARCHAR NOT NULL PRIMARY KEY,
    course_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY (course_id) REFERENCES courses (id)
);

CREATE INDEX IF NOT EXISTS ix_chapters_id ON chapters (id);
CREATE INDEX IF NOT EXISTS ix_chapters_course_id ON chapters (course_id);
CREATE INDEX IF NOT EXISTS ix_chapters_sort_order ON chapters (sort_order);

ALTER TABLE projects ADD COLUMN course_id VARCHAR;
ALTER TABLE projects ADD COLUMN chapter_id VARCHAR;
ALTER TABLE projects ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_projects_course_id ON projects (course_id);
CREATE INDEX IF NOT EXISTS ix_projects_chapter_id ON projects (chapter_id);
