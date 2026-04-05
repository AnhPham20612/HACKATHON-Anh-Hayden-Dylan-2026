import os
from psycopg2.extras import RealDictCursor
import psycopg2
from typing import Optional,List,Dict, Any
from datetime import datetime

DATABASE_URL = (
    "postgresql://neondb_owner:npg_AEQ8r5tXDhdg@"
    "ep-cool-bread-a8pe8h2p-pooler.eastus2.azure.neon.tech/"
    "neondb?sslmode=require&channel_binding=require"
)



def get_db_connection():
    """
    Create and return a PostgreSQL database connection
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise



def initialize_database():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Students table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS students (
                student_id SERIAL PRIMARY KEY,
                uop_id VARCHAR(50) UNIQUE NOT NULL,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                major VARCHAR(100),
                graduation_year INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        #courses table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                course_id SERIAL PRIMARY KEY,
                course_code VARCHAR(20) UNIQUE NOT NULL,
                course_name VARCHAR(255) NOT NULL,
                department VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

         # Assignments table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                assignment_id SERIAL PRIMARY KEY,
                course_id INTEGER REFERENCES courses(course_id) ON DELETE CASCADE,
                assignment_name VARCHAR(255) NOT NULL,
                description TEXT,
                semester VARCHAR(20),
                year INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Submissions table - stores student work
        cur.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                submission_id SERIAL PRIMARY KEY,
                student_id INTEGER REFERENCES students(student_id) ON DELETE CASCADE,
                assignment_id INTEGER REFERENCES assignments(assignment_id) ON DELETE CASCADE,
                file_name VARCHAR(255),
                file_path TEXT,
                content TEXT NOT NULL,
                submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                word_count INTEGER,
                UNIQUE(student_id, assignment_id)
            );
        """)

        # Plagiarism checks table - stores check results
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plagiarism_checks (
                check_id SERIAL PRIMARY KEY,
                checked_submission_id INTEGER REFERENCES submissions(submission_id) ON DELETE CASCADE,
                check_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                overall_similarity_score DECIMAL(5,2),
                status VARCHAR(50) DEFAULT 'completed'
            );
        """)

        # Similarity matches table - detailed matches
        cur.execute("""
            CREATE TABLE IF NOT EXISTS similarity_matches (
                match_id SERIAL PRIMARY KEY,
                check_id INTEGER REFERENCES plagiarism_checks(check_id) ON DELETE CASCADE,
                original_submission_id INTEGER REFERENCES submissions(submission_id) ON DELETE CASCADE,
                similarity_score DECIMAL(5,2) NOT NULL,
                matched_text_snippet TEXT,
                match_location TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Create indexes for better performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_submissions_student 
            ON submissions(student_id);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_submissions_assignment 
            ON submissions(assignment_id);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_plagiarism_checks_submission 
            ON plagiarism_checks(checked_submission_id);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_similarity_matches_check 
            ON similarity_matches(check_id);
        """)
        
        conn.commit()
        print("Database tables created successfully!")
    except Exception as e:
        conn.rollback()
        print(f"Error creating tables: {e}")
        raise
    finally:
        cur.close()
        conn.close()
        

    
class DataBaseManager():
    def __init__(self):
        self.connection_string = DATABASE_URL
    
    # Student Operations
    def add_student(self, uop_id: str, first_name: str, last_name: str, 
                   email: str, major: str = None, graduation_year: int = None) -> int:
        """Add a new student to the database"""
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO students (uop_id, first_name, last_name, email, major, graduation_year)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING student_id;
            """, (uop_id, first_name, last_name, email, major, graduation_year))
            
            student_id = cur.fetchone()[0]
            conn.commit()
            return student_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()
    def get_student(self, uop_id: str) -> Optional[Dict[str, Any]]:
        """Get student information by UOP ID"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM students WHERE uop_id = %s;", (uop_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
            conn.close()

    def get_student_by_id(self, student_id: int) -> Optional[Dict[str, Any]]:
        """Get student by internal student_id"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM students WHERE student_id = %s;", (student_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
            conn.close()

    def ensure_student_exists(self, student_id: int) -> bool:
        """Returns True if student_id exists. Use before add_submission to avoid FK crashes."""
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM students WHERE student_id = %s;", (student_id,))
            return cur.fetchone() is not None
        finally:
            cur.close()
            conn.close()

    def ensure_assignment_exists(self, assignment_id: int) -> bool:
        """Returns True if assignment_id exists. Use before add_submission to avoid FK crashes."""
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM assignments WHERE assignment_id = %s;", (assignment_id,))
            return cur.fetchone() is not None
        finally:
            cur.close()
            conn.close()

    def add_submission(self, student_id: int, assignment_id: int, 
                      content: str, file_name: str = None, 
                      file_path: str = None) -> int:
        """Add a new submission"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            word_count = len(content.split())
            
            cur.execute("""
                INSERT INTO submissions 
                (student_id, assignment_id, file_name, file_path, content, word_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_id, assignment_id)
                DO UPDATE SET
                    file_name = EXCLUDED.file_name,
                    file_path = EXCLUDED.file_path,
                    content = EXCLUDED.content,
                    word_count = EXCLUDED.word_count,
                    submission_date = CURRENT_TIMESTAMP
                RETURNING submission_id;
            """, (student_id, assignment_id, file_name, file_path, content, word_count))
            
            submission_id = cur.fetchone()[0]
            conn.commit()
            return submission_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()


    def get_all_submissions_for_assignment(self, assignment_id: int) -> List[Dict[str, Any]]:
        """Get all submissions for a specific assignment"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cur.execute("""
                SELECT s.*, st.first_name, st.last_name, st.uop_id
                FROM submissions s
                JOIN students st ON s.student_id = st.student_id
                WHERE s.assignment_id = %s
                ORDER BY s.submission_date DESC;
            """, (assignment_id,))
            
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
            conn.close()
    
    def create_plagiarism_check(self, submission_id: int, 
                               similarity_score: float) -> int:
        """Create a new plagiarism check record"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO plagiarism_checks 
                (checked_submission_id, overall_similarity_score)
                VALUES (%s, %s)
                RETURNING check_id;
            """, (submission_id, similarity_score))
            
            check_id = cur.fetchone()[0]
            conn.commit()
            return check_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    
    def add_similarity_match(self, check_id: int, original_submission_id: int,
                           similarity_score: float, matched_snippet: str = None,
                           match_location: str = None) -> int:
        """Add a similarity match record"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO similarity_matches 
                (check_id, original_submission_id, similarity_score, 
                 matched_text_snippet, match_location)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING match_id;
            """, (check_id, original_submission_id, similarity_score, 
                  matched_snippet, match_location))
            
            match_id = cur.fetchone()[0]
            conn.commit()
            return match_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()
    

    def get_plagiarism_report(self, submission_id: int) -> Dict[str, Any]:
        """Get complete plagiarism report for a submission"""
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Get check info
            cur.execute("""
                SELECT * FROM plagiarism_checks 
                WHERE checked_submission_id = %s
                ORDER BY check_date DESC
                LIMIT 1;
            """, (submission_id,))
            
            row = cur.fetchone()
            check = dict(row) if row else None


            if not check:
                return None
            
            # Get all matches
            cur.execute("""
                SELECT sm.*, s.file_name, st.first_name, st.last_name, st.uop_id
                FROM similarity_matches sm
                JOIN submissions s ON sm.original_submission_id = s.submission_id
                JOIN students st ON s.student_id = st.student_id
                WHERE sm.check_id = %s
                ORDER BY sm.similarity_score DESC;
            """, (check['check_id'],))
            
            matches = [dict(row) for row in cur.fetchall()]
            
            return {
                'check_info': check,
                'matches': matches
            }
        finally:
            cur.close()
            conn.close()



    def get_or_create_student(self, uop_id: str, first_name: str,
                              last_name: str, email: str,
                              major: str = None, graduation_year: int = None) -> int:
        """
        Returns the student_id for an existing student, or creates and
        returns a new one. Prevents duplicate-insert errors when the same
        student submits more than once.
        """
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT student_id FROM students WHERE uop_id = %s;", (uop_id,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute("""
                INSERT INTO students (uop_id, first_name, last_name, email, major, graduation_year)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING student_id;
            """, (uop_id, first_name, last_name, email, major, graduation_year))
            student_id = cur.fetchone()[0]
            conn.commit()
            return student_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def get_or_create_assignment(self, course_id: int, assignment_name: str,
                                  semester: str = None, year: int = None) -> int:
        """
        Returns the assignment_id for an existing assignment in a course,
        or creates and returns a new one.
        """
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT assignment_id FROM assignments
                WHERE course_id = %s AND assignment_name = %s;
            """, (course_id, assignment_name))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute("""
                INSERT INTO assignments (course_id, assignment_name, semester, year)
                VALUES (%s, %s, %s, %s)
                RETURNING assignment_id;
            """, (course_id, assignment_name, semester, year))
            assignment_id = cur.fetchone()[0]
            conn.commit()
            return assignment_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def get_or_create_course(self, course_code: str, course_name: str,
                              department: str = None) -> int:
        """
        Returns the course_id for an existing course, or creates and
        returns a new one.
        """
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT course_id FROM courses WHERE course_code = %s;", (course_code,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute("""
                INSERT INTO courses (course_code, course_name, department)
                VALUES (%s, %s, %s)
                RETURNING course_id;
            """, (course_code, course_name, department))
            course_id = cur.fetchone()[0]
            conn.commit()
            return course_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def seed_demo_data(self):
        """
        Ensures student_id=1 and assignment_id=1 exist so the frontend
        demo works out of the box without manually inserting rows first.
        Safe to call repeatedly — uses INSERT ... ON CONFLICT DO NOTHING.
        After inserting, resets SERIAL sequences so new rows get IDs > 1
        and don't collide with the seed data.
        """
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Demo course
            cur.execute("""
                INSERT INTO courses (course_id, course_code, course_name, department)
                VALUES (1, 'DEMO-101', 'PacificCheck Demo Course', 'Academic Integrity')
                ON CONFLICT (course_code) DO NOTHING;
            """)
            # Demo assignment
            cur.execute("""
                INSERT INTO assignments (assignment_id, course_id, assignment_name, semester, year)
                VALUES (1, 1, 'Demo Assignment', 'Spring', 2026)
                ON CONFLICT DO NOTHING;
            """)
            # Demo student
            cur.execute("""
                INSERT INTO students (student_id, uop_id, first_name, last_name, email)
                VALUES (1, 'DEMO001', 'Demo', 'Student', 'demo@u.pacific.edu')
                ON CONFLICT DO NOTHING;
            """)

            # CRITICAL: reset sequences so the next auto-generated ID starts
            # above 1. Without this, any INSERT that relies on SERIAL will try
            # to use ID 1 again and crash with a duplicate key error — which is
            # why student_id and assignment_id were stuck at 1.
            cur.execute("SELECT setval('students_student_id_seq', MAX(student_id)) FROM students;")
            cur.execute("SELECT setval('courses_course_id_seq', MAX(course_id)) FROM courses;")
            cur.execute("SELECT setval('assignments_assignment_id_seq', MAX(assignment_id)) FROM assignments;")

            conn.commit()
            print('Demo seed data ready. Sequences reset.')
        except Exception as e:
            conn.rollback()
            print(f'Seed warning (non-fatal): {e}')
        finally:
            cur.close()
            conn.close()

def test_connection():
    """Test database connection"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"Connected successfully! PostgreSQL version: {version[0]}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False
    

if __name__ == "__main__":
    print("Testing database connection...")
    if test_connection():
        print("\nInitializing database schema...")
        initialize_database()
        print("\nDatabase setup complete!")
        
        # Example usage
        print("\nExample: Creating a database manager instance...")
        db = DataBaseManager()
        print("Ready to use!")
