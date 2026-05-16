"""
ATS Pro v2 - Two-flow Applicant Tracking System
  Flow 1 — Guest:   No account, instant resume ATS check + language fixes
  Flow 2 — Company: Registered account, full hiring dashboard + compare
"""
import os, json, sqlite3, hashlib, uuid, re, hmac as _hmac, base64, time
from functools import wraps
from flask import Flask, request, jsonify, render_template, g
import urllib.request

app = Flask(__name__)
app.config['SECRET_KEY']         = os.environ.get('SECRET_KEY', 'ats-pro-2026-change-me')
app.config['DATABASE']           = os.path.join(os.path.dirname(__file__), 'ats_pro.db')
app.config['UPLOAD_FOLDER']      = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
app.config['ANTHROPIC_API_KEY']  = os.environ.get('ANTHROPIC_API_KEY', '')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ── DB ─────────────────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            company TEXT DEFAULT '', industry TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS job_roles (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
            emoji TEXT DEFAULT '💼', title TEXT NOT NULL,
            department TEXT DEFAULT 'General', description TEXT DEFAULT '',
            required_skills TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
            name TEXT NOT NULL, email TEXT DEFAULT '', role TEXT NOT NULL,
            filename TEXT DEFAULT '', resume_text TEXT DEFAULT '',
            ats_score INTEGER DEFAULT 0, grade TEXT DEFAULT '',
            skills_score INTEGER DEFAULT 0, experience_score INTEGER DEFAULT 0,
            keywords_score INTEGER DEFAULT 0, format_score INTEGER DEFAULT 0,
            matched_skills TEXT DEFAULT '[]', missing_skills TEXT DEFAULT '[]',
            bonus_skills TEXT DEFAULT '[]', eligible_companies TEXT DEFAULT '[]',
            interview_questions TEXT DEFAULT '[]', roadmap TEXT DEFAULT '[]',
            summary TEXT DEFAULT '', recommendations TEXT DEFAULT '',
            hire_recommendation TEXT DEFAULT 'Pending',
            hire_reasoning TEXT DEFAULT '', red_flags TEXT DEFAULT '[]',
            green_flags TEXT DEFAULT '[]', status TEXT DEFAULT 'New',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS comparisons (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, role TEXT NOT NULL,
            candidate_ids TEXT DEFAULT '[]', ai_summary TEXT DEFAULT '',
            recommendation TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()
    _seed_roles(db)
    db.close()

def _seed_roles(db):
    defaults = [
        ('⚛️','Frontend Developer','Engineering','React,TypeScript,JavaScript,CSS,HTML,Jest,REST APIs'),
        ('⚙️','Backend Developer','Engineering','Python,Node.js,SQL,PostgreSQL,Docker,AWS,REST APIs'),
        ('🔗','Full Stack Developer','Engineering','React,Node.js,TypeScript,PostgreSQL,Docker,CI/CD'),
        ('📊','Data Scientist','Analytics','Python,ML,Pandas,NumPy,SQL,TensorFlow,Matplotlib'),
        ('🤖','ML Engineer','AI/ML','PyTorch,TensorFlow,Python,MLOps,Docker,CUDA'),
        ('🐳','DevOps Engineer','Operations','Docker,Kubernetes,CI/CD,Terraform,AWS,Linux'),
        ('📋','Product Manager','Product','Roadmapping,Agile,Stakeholder Management,SQL,Figma'),
        ('🎨','UI/UX Designer','Design','Figma,User Research,Prototyping,CSS,Adobe XD'),
    ]
    for emoji, title, dept, skills in defaults:
        if not db.execute("SELECT id FROM job_roles WHERE title=? AND company_id='system'",(title,)).fetchone():
            db.execute("INSERT INTO job_roles(id,company_id,emoji,title,department,required_skills) VALUES(?,?,?,?,?,?)",
                       (str(uuid.uuid4()),'system',emoji,title,dept,json.dumps(skills.split(','))))
    db.commit()

# ── Auth ───────────────────────────────────────────────────────────────────────
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def make_token(uid):
    hdr = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip('=')
    pay = base64.urlsafe_b64encode(json.dumps({"sub":uid,"exp":int(time.time())+86400*7}).encode()).decode().rstrip('=')
    sig = base64.urlsafe_b64encode(_hmac.new(app.config['SECRET_KEY'].encode(),f"{hdr}.{pay}".encode(),'sha256').digest()).decode().rstrip('=')
    return f"{hdr}.{pay}.{sig}"

def verify_token(token):
    try:
        hdr, pay, sig = token.split('.')
        exp_sig = base64.urlsafe_b64encode(_hmac.new(app.config['SECRET_KEY'].encode(),f"{hdr}.{pay}".encode(),'sha256').digest()).decode().rstrip('=')
        if sig != exp_sig: return None
        data = json.loads(base64.urlsafe_b64decode(pay + '=='*3))
        return data['sub'] if data.get('exp',0) > time.time() else None
    except: return None

def require_auth(f):
    @wraps(f)
    def dec(*a, **kw):
        auth = request.headers.get('Authorization','')
        token = auth[7:] if auth.startswith('Bearer ') else ''
        uid = verify_token(token)
        if not uid: return jsonify({'error':'Authentication required'}), 401
        row = get_db().execute("SELECT * FROM companies WHERE id=?", (uid,)).fetchone()
        if not row: return jsonify({'error':'Not found'}), 401
        g.company = dict(row)
        return f(*a, **kw)
    return dec

# ── File / text extraction ─────────────────────────────────────────────────────
def extract_text(path, filename):
    ext = filename.rsplit('.',1)[-1].lower()
    try:
        if ext == 'pdf':
            from pypdf import PdfReader
            return '\n'.join(p.extract_text() or '' for p in PdfReader(path).pages)
        elif ext == 'docx':
            from docx import Document
            return '\n'.join(p.text for p in Document(path).paragraphs)
        else:
            with open(path,'r',errors='ignore') as f: return f.read()
    except Exception as e: return f'[Error: {e}]'

# ── Claude AI ──────────────────────────────────────────────────────────────────
def call_claude(system, user, max_tokens=1600):
    key = app.config['ANTHROPIC_API_KEY']
    if not key: raise ValueError("No API key")
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=json.dumps({"model":"claude-sonnet-4-20250514","max_tokens":max_tokens,
                         "system":system,"messages":[{"role":"user","content":user}]}).encode(),
        headers={'Content-Type':'application/json','x-api-key':key,'anthropic-version':'2023-06-01'},
        method='POST')
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = ''.join(b.get('text','') for b in json.loads(r.read()).get('content',[]))
    raw = re.sub(r'^```json\s*','',raw.strip())
    raw = re.sub(r'\s*```$','',raw.strip())
    return json.loads(raw)

def ai_guest_overall(text):
    return call_claude(
        "You are an ATS expert. Return ONLY valid JSON. No markdown. No explanation.",
        f"""Analyze this resume for overall ATS optimization.

Resume:
{text[:3500]}

Return ONLY this JSON:
{{
  "candidate_name": "<name or Candidate>",
  "overall_score": <0-100>,
  "grade": "<Excellent|Good|Average|Below Average|Poor>",
  "content_score": <0-100>,
  "format_score": <0-100>,
  "language_score": <0-100>,
  "keyword_score": <0-100>,
  "estimated_pass_rate": <0-100>,
  "summary": "<3 sentences: strengths and what needs work>",
  "strengths": ["strength1","strength2","strength3"],
  "weaknesses": ["weakness1","weakness2","weakness3"],
  "language_issues": [{{"issue":"<issue>","fix":"<how to fix>","severity":"High|Medium|Low"}},...],
  "missing_sections": ["Section Name",...],
  "ats_keywords_found": ["kw1","kw2",...],
  "ats_keywords_missing": ["kw1","kw2",...],
  "formatting_tips": ["tip1","tip2","tip3",...],
  "rewrite_suggestions": [{{"original":"<text>","improved":"<better text>","reason":"why"}},...],
  "action_items": [{{"priority":1,"action":"<do this>","impact":"High|Medium|Low"}},...],
  "word_choice_improvements": [{{"weak":"<weak word>","strong":"<strong alternative>"}},...],
  "overall_verdict": "<one line overall verdict>"
}}"""
    )

def ai_guest_role(text, role):
    return call_claude(
        "You are an ATS expert. Return ONLY valid JSON. No markdown.",
        f"""Analyze this resume specifically for the role: "{role}"

Resume:
{text[:3500]}

Return ONLY this JSON:
{{
  "candidate_name": "<name or Candidate>",
  "role_fit_score": <0-100>,
  "grade": "<Excellent|Good|Average|Below Average|Poor>",
  "skills_score": <0-100>,
  "experience_score": <0-100>,
  "keywords_score": <0-100>,
  "format_score": <0-100>,
  "estimated_ats_pass_rate": <0-100>,
  "summary": "<3 sentences about fit for this specific role>",
  "matched_skills": ["skill1",...],
  "missing_skills": ["skill1",...],
  "bonus_skills": ["skill1",...],
  "experience_gaps": ["gap1",...],
  "language_improvements": [{{"section":"<section>","issue":"<issue>","suggestion":"<improved text>"}},...],
  "keyword_recommendations": ["Add keyword X","Replace Y with Z",...],
  "formatting_issues": ["issue1",...],
  "action_items": [{{"priority":1,"action":"<do this for {role}>","impact":"High|Medium|Low"}},...],
  "word_choice_improvements": [{{"weak":"<word>","strong":"<better word>"}},...],
  "interview_readiness": "<Low|Medium|High>",
  "top_tip": "<single most impactful change to make>",
  "rewrite_suggestions": [{{"section":"<section>","original":"<text>","improved":"<better text>"}},...],
  "overall_verdict": "<one line verdict>"
}}"""
    )

def ai_company_analyze(text, role, exp, jd=''):
    jd_part = f"\nJob Description:\n{jd[:1500]}" if jd else ""
    return call_claude(
        "You are a senior HR analyst and ATS expert. Return ONLY valid JSON. No markdown.",
        f"""Analyze this resume for hiring as "{role}" ({exp}).{jd_part}

Resume:
{text[:3500]}

Return ONLY this JSON:
{{
  "candidate_name": "<from resume or Candidate>",
  "candidate_email": "<email or empty>",
  "score": <0-100>,
  "grade": "<Excellent|Good|Average|Below Average|Poor>",
  "skills_score": <0-100>,
  "experience_score": <0-100>,
  "keywords_score": <0-100>,
  "format_score": <0-100>,
  "summary": "<3-4 sentences on suitability for this role>",
  "matched_skills": ["skill1",...],
  "missing_skills": ["skill1",...],
  "bonus_skills": ["skill1",...],
  "eligible_companies": [{{"name":"Co","tier":"Tier 1|2|3","reason":"why"}},...],
  "interview_questions": [{{"question":"Q?","difficulty":"Easy|Medium|Hard","topic":"topic"}},...],
  "roadmap": [{{"step":1,"title":"Action","description":"Detail","priority":"High|Medium|Low"}},...],
  "recommendations": "<concrete improvement suggestions>",
  "hire_recommendation": "<Strong Hire|Hire|Maybe|Reject>",
  "hire_reasoning": "<why this recommendation in 2 sentences>",
  "red_flags": ["flag1",...],
  "green_flags": ["flag1",...]
}}""", max_tokens=1800)

def ai_compare(candidates, role):
    cands_txt = "\n\n".join([
        f"Candidate {i+1}: {c['name']} | Score: {c['ats_score']}% | Grade: {c['grade']}\nMatched Skills: {', '.join(c.get('matched_skills',[])[:6])}\nMissing Skills: {', '.join(c.get('missing_skills',[])[:5])}\nSummary: {c['summary']}\nHire Rec: {c.get('hire_recommendation','Pending')}"
        for i, c in enumerate(candidates)])
    return call_claude(
        "You are a senior hiring manager. Return ONLY valid JSON. No markdown.",
        f"""Compare {len(candidates)} candidates for the role "{role}" and give hiring recommendations.

{cands_txt}

Return ONLY this JSON:
{{
  "ranking": [{{"rank":1,"candidate_name":"Name","score":<n>,"verdict":"Interview|Shortlist|Reject|Hold","reason":"<2 sentences why>"}},...],
  "top_pick": "<best candidate name>",
  "interview_list": ["name1",...],
  "shortlist_list": ["name1",...],
  "reject_list": ["name1",...],
  "hold_list": ["name1",...],
  "comparison_summary": "<3-4 sentences comparing this pool>",
  "role_fit_analysis": "<who fits best and why>",
  "skills_comparison": "<key skill differences between candidates>",
  "hiring_risk": "<Low|Medium|High>",
  "recommendation": "<final paragraph: who to call, who to skip, next steps>"
}}""", max_tokens=1200)

# ── Fallbacks ──────────────────────────────────────────────────────────────────
def _fb_overall(s):
    return {"candidate_name":"Candidate","overall_score":s,"grade":"Good" if s>=65 else "Average",
            "content_score":s+3,"format_score":s-5,"language_score":s+7,"keyword_score":s-2,"estimated_pass_rate":s-10,
            "summary":"The resume has a solid foundation but needs targeted improvements. Several sections lack quantifiable achievements. ATS optimization would significantly improve pass rates.",
            "strengths":["Relevant work experience","Clear contact information","Education details present"],
            "weaknesses":["Lacks quantifiable achievements","Missing action verbs","Generic summary section"],
            "language_issues":[{"issue":"Passive voice overuse","fix":"Use action verbs like Led, Built, Achieved","severity":"High"},{"issue":"Vague descriptions","fix":"Add specific metrics and outcomes","severity":"High"}],
            "missing_sections":["Professional Summary","Skills Section"],"ats_keywords_found":["experience","skills"],"ats_keywords_missing":["leadership","agile","data-driven"],
            "formatting_tips":["Use consistent bullet points","Add section dividers","Keep to 1-2 pages"],
            "rewrite_suggestions":[{"original":"Responsible for managing team","improved":"Led 5-member team to deliver project 2 weeks ahead of schedule","reason":"Quantified and uses action verb"}],
            "action_items":[{"priority":1,"action":"Add quantifiable achievements to each role","impact":"High"},{"priority":2,"action":"Include a strong professional summary","impact":"High"}],
            "word_choice_improvements":[{"weak":"responsible for","strong":"led / managed / oversaw"},{"weak":"helped with","strong":"contributed to / accelerated"}],
            "overall_verdict":"Strong candidate with room for ATS optimization — focus on quantification and keywords."}

def _fb_role(s, role):
    return {"candidate_name":"Candidate","role_fit_score":s,"grade":"Good" if s>=65 else "Average",
            "skills_score":s+5,"experience_score":s-8,"keywords_score":s,"format_score":s+8,"estimated_ats_pass_rate":s-5,
            "summary":f"Candidate shows partial fit for {role}. Key technical skills present but modern tooling knowledge limited. Targeted upskilling would make this a stronger application.",
            "matched_skills":["Communication","Problem Solving","Git","Documentation"],"missing_skills":["Docker","CI/CD","Cloud Platform","TypeScript"],"bonus_skills":["Agile"],
            "experience_gaps":["No production-scale project experience"],"language_improvements":[{"section":"Work Experience","issue":"Vague responsibilities","suggestion":"Quantify achievements with numbers"}],
            "keyword_recommendations":[f"Add '{role}' in your headline","Include specific framework names"],"formatting_issues":["Skills section needs better organization"],
            "action_items":[{"priority":1,"action":f"Learn top 3 missing skills for {role}","impact":"High"},{"priority":2,"action":"Rewrite experience bullets with metrics","impact":"High"}],
            "word_choice_improvements":[{"weak":"worked on","strong":"engineered / built / shipped"}],"interview_readiness":"Medium",
            "top_tip":f"Add the exact job title '{role}' in your professional headline for better ATS matching.",
            "rewrite_suggestions":[{"section":"Summary","original":"Experienced developer looking for opportunities","improved":f"Results-driven {role} with 3+ years building scalable applications"}],
            "overall_verdict":f"Decent fit for {role} — add missing skills and quantify achievements to stand out."}

def _fb_company(s, role):
    return {"candidate_name":"Candidate","candidate_email":"","score":s,
            "grade":"Good" if s>=65 else "Average","skills_score":min(s+5,100),"experience_score":max(s-8,0),"keywords_score":s,"format_score":min(s+10,100),
            "summary":f"Candidate shows solid potential for {role}. Technical foundation present with some gaps in advanced tooling. Recommended for a technical screening call.",
            "matched_skills":["Communication","Problem Solving","Git","REST APIs"],"missing_skills":["Docker","CI/CD","AWS","TypeScript"],"bonus_skills":["Agile"],
            "eligible_companies":[{"name":"TCS","tier":"Tier 2","reason":"Good entry fit"},{"name":"Infosys","tier":"Tier 2","reason":"Stack match"},{"name":"Accenture","tier":"Tier 1","reason":"Consulting potential"}],
            "interview_questions":[{"question":f"Describe your most challenging {role} project.","difficulty":"Medium","topic":"Experience"},{"question":"How do you debug production issues?","difficulty":"Hard","topic":"Technical"}],
            "roadmap":[{"step":1,"title":"Add quantifiable achievements","description":"Replace vague bullets with measurable outcomes.","priority":"High"}],
            "recommendations":"Add metrics to experience. Learn cloud/DevOps basics.",
            "hire_recommendation":"Maybe","hire_reasoning":"Candidate meets basic requirements but lacks advanced skills. Recommend technical screening.",
            "red_flags":["No cloud experience","Vague project descriptions"],"green_flags":["Consistent work history","Relevant education"]}

def _fb_compare(candidates, role):
    ranked = sorted(candidates, key=lambda x: x['ats_score'], reverse=True)
    return {"ranking":[{"rank":i+1,"candidate_name":c['name'],"score":c['ats_score'],
                        "verdict":"Interview" if c['ats_score']>=70 else "Shortlist" if c['ats_score']>=55 else "Reject",
                        "reason":f"Score of {c['ats_score']}% {'exceeds' if c['ats_score']>=70 else 'meets' if c['ats_score']>=55 else 'falls below'} the threshold."} for i,c in enumerate(ranked)],
            "top_pick":ranked[0]['name'],
            "interview_list":[c['name'] for c in ranked if c['ats_score']>=70],
            "shortlist_list":[c['name'] for c in ranked if 55<=c['ats_score']<70],
            "reject_list":[c['name'] for c in ranked if c['ats_score']<55],
            "hold_list":[],"comparison_summary":f"Pool of {len(candidates)} candidates reviewed. Top candidate scored {ranked[0]['ats_score']}%. Significant skill variation observed across candidates.",
            "role_fit_analysis":f"{ranked[0]['name']} is the best fit with the highest ATS score and most matched skills.",
            "skills_comparison":"Candidates vary significantly in technical depth and modern tooling experience.","hiring_risk":"Medium",
            "recommendation":f"Proceed with {ranked[0]['name']} for a technical interview. Consider {ranked[1]['name'] if len(ranked)>1 else 'other candidates'} as backup. Reject low scorers unless pipeline is thin."}

# ══════════════════════════════════════════════════════════════════════════════
# PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def home(): return render_template('home.html')

@app.route('/check')
def check_page(): return render_template('guest_check.html')

@app.route('/company/login')
def company_login(): return render_template('company_login.html')

@app.route('/company/register')
def company_register(): return render_template('company_register.html')

@app.route('/company')
def company_dashboard(): return render_template('company_index.html')

@app.route('/company/analyze')
def company_analyze(): return render_template('company_analyze.html')

@app.route('/company/candidates')
def company_candidates(): return render_template('company_candidates.html')

@app.route('/company/compare')
def company_compare(): return render_template('company_compare.html')

@app.route('/company/analytics')
def company_analytics(): return render_template('company_analytics.html')

@app.route('/company/jobs')
def company_jobs(): return render_template('company_jobs.html')


# ══════════════════════════════════════════════════════════════════════════════
# GUEST API
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/guest/check', methods=['POST'])
def api_guest_check():
    if 'resume' not in request.files: return jsonify({'error':'No file'}), 400
    file  = request.files['resume']
    role  = request.form.get('role','').strip()
    ctype = request.form.get('check_type','overall')

    safe = f"{uuid.uuid4()}_{file.filename.replace(' ','_')}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], safe)
    file.save(path)
    text = extract_text(path, file.filename)
    try: os.remove(path)
    except: pass

    if len(text.strip()) < 30: text = f"[File: {file.filename}]"
    try:
        result = ai_guest_overall(text) if ctype == 'overall' else ai_guest_role(text, role)
    except:
        import random; s = random.randint(45,75)
        result = _fb_overall(s) if ctype == 'overall' else _fb_role(s, role)

    return jsonify({'success':True,'result':result,'check_type':ctype,'role':role})


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY AUTH
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/company/register', methods=['POST'])
def api_register():
    d = request.get_json()
    name,email,pw = (d.get('name','') or '').strip(), (d.get('email','') or '').strip().lower(), d.get('password','')
    if not name or not email or not pw: return jsonify({'error':'Name, email, password required'}), 400
    if len(pw) < 6: return jsonify({'error':'Password min 6 chars'}), 400
    db = get_db()
    if db.execute("SELECT id FROM companies WHERE email=?",(email,)).fetchone():
        return jsonify({'error':'Email already registered'}), 409
    cid = str(uuid.uuid4())
    db.execute("INSERT INTO companies(id,name,email,password,company,industry) VALUES(?,?,?,?,?,?)",
               (cid,name,email,hash_pw(pw),d.get('company',''),d.get('industry','')))
    db.commit()
    return jsonify({'token':make_token(cid),'company':{'id':cid,'name':name,'email':email,'company':d.get('company','')}}), 201

@app.route('/api/company/login', methods=['POST'])
def api_login():
    d = request.get_json()
    email, pw = (d.get('email','') or '').strip().lower(), d.get('password','')
    db = get_db()
    row = db.execute("SELECT * FROM companies WHERE email=?",(email,)).fetchone()
    if not row or row['password'] != hash_pw(pw): return jsonify({'error':'Invalid credentials'}), 401
    return jsonify({'token':make_token(row['id']),'company':{'id':row['id'],'name':row['name'],'email':row['email'],'company':row['company']}})

@app.route('/api/company/me')
@require_auth
def api_me(): return jsonify({'company':g.company})


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY — ANALYZE
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/company/analyze', methods=['POST'])
@require_auth
def api_analyze():
    if 'resume' not in request.files: return jsonify({'error':'No file'}), 400
    file = request.files['resume']
    role = request.form.get('role','Software Engineer')
    exp  = request.form.get('experience_level','Mid Level (2-5 years)')
    jd   = request.form.get('job_description','')

    safe = f"{uuid.uuid4()}_{file.filename.replace(' ','_')}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], safe)
    file.save(path)
    text = extract_text(path, file.filename)
    try: os.remove(path)
    except: pass
    if len(text.strip()) < 30: text = f"[File: {file.filename}]"

    try:
        r = ai_company_analyze(text, role, exp, jd)
    except:
        import random; r = _fb_company(random.randint(50,84), role)

    db  = get_db()
    cid = str(uuid.uuid4())
    db.execute("""INSERT INTO candidates
        (id,company_id,name,email,role,filename,resume_text,ats_score,grade,
         skills_score,experience_score,keywords_score,format_score,
         matched_skills,missing_skills,bonus_skills,eligible_companies,
         interview_questions,roadmap,summary,recommendations,
         hire_recommendation,hire_reasoning,red_flags,green_flags)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cid,g.company['id'],r.get('candidate_name','Candidate'),r.get('candidate_email',''),
         role,file.filename,text[:5000],r.get('score',0),r.get('grade',''),
         r.get('skills_score',0),r.get('experience_score',0),r.get('keywords_score',0),r.get('format_score',0),
         json.dumps(r.get('matched_skills',[])),json.dumps(r.get('missing_skills',[])),
         json.dumps(r.get('bonus_skills',[])),json.dumps(r.get('eligible_companies',[])),
         json.dumps(r.get('interview_questions',[])),json.dumps(r.get('roadmap',[])),
         r.get('summary',''),r.get('recommendations',''),r.get('hire_recommendation','Pending'),
         r.get('hire_reasoning',''),json.dumps(r.get('red_flags',[])),json.dumps(r.get('green_flags',[]))))
    db.commit()
    r['id'] = cid
    return jsonify({'success':True,'candidate':r})


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY — CANDIDATES CRUD
# ══════════════════════════════════════════════════════════════════════════════
def _parse(row):
    c = dict(row)
    for f in ['matched_skills','missing_skills','bonus_skills','eligible_companies','interview_questions','roadmap','red_flags','green_flags']:
        try: c[f] = json.loads(c[f])
        except: c[f] = []
    return c

@app.route('/api/company/candidates')
@require_auth
def api_candidates():
    db = get_db()
    q = "SELECT * FROM candidates WHERE company_id=?"; p = [g.company['id']]
    for field, col in [('search',None),('role','role'),('grade','grade'),('status','status'),('hire','hire_recommendation')]:
        val = request.args.get(field,'')
        if val and col: q += f" AND {col}=?"; p.append(val)
    if request.args.get('search',''):
        s = request.args['search']
        q += " AND (name LIKE ? OR role LIKE ? OR email LIKE ?)"; p += [f'%{s}%']*3
    sort = request.args.get('sort','created_at')
    if sort not in {'created_at','ats_score','name','role'}: sort='created_at'
    q += f" ORDER BY {sort} {'DESC' if request.args.get('order','desc')=='desc' else 'ASC'}"
    rows = db.execute(q,p).fetchall()
    return jsonify({'candidates':[_parse(r) for r in rows],'total':len(rows)})

@app.route('/api/company/candidates/<cid>')
@require_auth
def api_candidate(cid):
    row = get_db().execute("SELECT * FROM candidates WHERE id=? AND company_id=?",(cid,g.company['id'])).fetchone()
    if not row: return jsonify({'error':'Not found'}),404
    return jsonify({'candidate':_parse(row)})

@app.route('/api/company/candidates/<cid>', methods=['DELETE'])
@require_auth
def api_del_candidate(cid):
    db = get_db(); db.execute("DELETE FROM candidates WHERE id=? AND company_id=?",(cid,g.company['id'])); db.commit()
    return jsonify({'success':True})

@app.route('/api/company/candidates/<cid>/update', methods=['PATCH'])
@require_auth
def api_update_candidate(cid):
    d = request.get_json(); db = get_db()
    for field in ['status','hire_recommendation','notes']:
        if field in d:
            db.execute(f"UPDATE candidates SET {field}=? WHERE id=? AND company_id=?",(d[field],cid,g.company['id']))
    db.commit()
    return jsonify({'success':True})


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY — COMPARE
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/company/compare', methods=['POST'])
@require_auth
def api_compare_route():
    d    = request.get_json()
    ids  = d.get('candidate_ids',[])
    role = d.get('role','')
    if len(ids) < 2: return jsonify({'error':'Select at least 2 candidates'}), 400

    db   = get_db()
    rows = db.execute(f"SELECT * FROM candidates WHERE id IN ({','.join('?'*len(ids))}) AND company_id=?",
                      ids+[g.company['id']]).fetchall()
    cands = [_parse(r) for r in rows]
    if not cands: return jsonify({'error':'Candidates not found'}),404
    if not role: role = cands[0]['role']

    try:
        result = ai_compare(cands, role)
    except:
        result = _fb_compare(cands, role)

    comp_id = str(uuid.uuid4())
    db.execute("INSERT INTO comparisons(id,company_id,role,candidate_ids,ai_summary,recommendation) VALUES(?,?,?,?,?,?)",
               (comp_id,g.company['id'],role,json.dumps(ids),result.get('comparison_summary',''),result.get('recommendation','')))
    db.commit()
    return jsonify({'success':True,'comparison':result,'candidates':cands})


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY — JOBS
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/company/jobs')
@require_auth
def api_jobs():
    db   = get_db()
    rows = db.execute("SELECT * FROM job_roles WHERE company_id='system' OR company_id=? ORDER BY created_at",(g.company['id'],)).fetchall()
    jobs = []
    for row in rows:
        j = dict(row)
        try: j['required_skills'] = json.loads(j['required_skills'])
        except: j['required_skills'] = []
        j['candidate_count'] = db.execute("SELECT COUNT(*) FROM candidates WHERE company_id=? AND role=?",(g.company['id'],j['title'])).fetchone()[0]
        j['avg_score']       = db.execute("SELECT AVG(ats_score) FROM candidates WHERE company_id=? AND role=?",(g.company['id'],j['title'])).fetchone()[0] or 0
        jobs.append(j)
    return jsonify({'jobs':jobs})

@app.route('/api/company/jobs', methods=['POST'])
@require_auth
def api_create_job():
    d = request.get_json(); title = (d.get('title','') or '').strip()
    if not title: return jsonify({'error':'Title required'}),400
    skills = d.get('required_skills',[])
    if isinstance(skills,str): skills=[s.strip() for s in skills.split(',') if s.strip()]
    jid = str(uuid.uuid4()); db = get_db()
    db.execute("INSERT INTO job_roles(id,company_id,emoji,title,department,description,required_skills) VALUES(?,?,?,?,?,?,?)",
               (jid,g.company['id'],d.get('emoji','💼'),title,d.get('department','General'),d.get('description',''),json.dumps(skills)))
    db.commit()
    return jsonify({'success':True,'job':{'id':jid,'title':title}}),201

@app.route('/api/company/jobs/<jid>', methods=['DELETE'])
@require_auth
def api_del_job(jid):
    db = get_db(); r = db.execute("DELETE FROM job_roles WHERE id=? AND company_id=?",(jid,g.company['id'])); db.commit()
    if r.rowcount==0: return jsonify({'error':'Cannot delete system roles'}),404
    return jsonify({'success':True})


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY — DASHBOARD + ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/company/dashboard')
@require_auth
def api_dashboard():
    db=get_db(); cid=g.company['id']
    total     = db.execute("SELECT COUNT(*) FROM candidates WHERE company_id=?",(cid,)).fetchone()[0]
    avg       = db.execute("SELECT AVG(ats_score) FROM candidates WHERE company_id=?",(cid,)).fetchone()[0] or 0
    excellent = db.execute("SELECT COUNT(*) FROM candidates WHERE company_id=? AND ats_score>=80",(cid,)).fetchone()[0]
    to_hire   = db.execute("SELECT COUNT(*) FROM candidates WHERE company_id=? AND hire_recommendation IN ('Strong Hire','Hire')",(cid,)).fetchone()[0]
    recent    = [_parse(r) for r in db.execute("SELECT * FROM candidates WHERE company_id=? ORDER BY created_at DESC LIMIT 6",(cid,)).fetchall()]
    return jsonify({'total':total,'avg_score':round(avg),'excellent':excellent,'to_hire':to_hire,'recent':recent})

@app.route('/api/company/analytics')
@require_auth
def api_analytics():
    db=get_db(); cid=g.company['id']
    rows=[dict(r) for r in db.execute("SELECT * FROM candidates WHERE company_id=? ORDER BY created_at",(cid,)).fetchall()]
    total=len(rows)
    if total==0: return jsonify({'total':0,'avg_score':0,'excellent':0,'roles_count':0,'score_dist':{},'role_dist':{},'trend':[],'skill_gaps':{},'company_freq':{},'status_dist':{},'hire_dist':{},'avg_by_role':{}})
    avg=round(sum(r['ats_score'] for r in rows)/total)
    excellent=sum(1 for r in rows if r['ats_score']>=80)
    roles=list({r['role'] for r in rows})
    score_dist={'Poor (<40)':sum(1 for r in rows if r['ats_score']<40),'Low (40-54)':sum(1 for r in rows if 40<=r['ats_score']<55),
                'Average (55-69)':sum(1 for r in rows if 55<=r['ats_score']<70),'Good (70-84)':sum(1 for r in rows if 70<=r['ats_score']<85),'Excellent (85+)':sum(1 for r in rows if r['ats_score']>=85)}
    role_dist={}
    for r in rows: role_dist[r['role']]=role_dist.get(r['role'],0)+1
    trend=[{'date':r['created_at'][:10],'score':r['ats_score'],'role':r['role'],'name':r['name']} for r in rows[-20:]]
    skill_gaps={}
    for r in rows:
        try:
            for s in json.loads(r['missing_skills']): skill_gaps[s]=skill_gaps.get(s,0)+1
        except: pass
    co_freq={}
    for r in rows:
        try:
            for co in json.loads(r['eligible_companies']):
                n=co.get('name',co) if isinstance(co,dict) else co; co_freq[n]=co_freq.get(n,0)+1
        except: pass
    status_dist={}
    for r in rows: status_dist[r['status']]=status_dist.get(r['status'],0)+1
    hire_dist={}
    for r in rows: hire_dist[r['hire_recommendation']]=hire_dist.get(r['hire_recommendation'],0)+1
    avg_by_role={role:round(sum(r['ats_score'] for r in rows if r['role']==role)/len([r for r in rows if r['role']==role])) for role in roles}
    return jsonify({'total':total,'avg_score':avg,'excellent':excellent,'roles_count':len(roles),'score_dist':score_dist,'role_dist':role_dist,'trend':trend,'skill_gaps':skill_gaps,'company_freq':co_freq,'status_dist':status_dist,'hire_dist':hire_dist,'avg_by_role':avg_by_role})

@app.route('/api/health')
def health(): return jsonify({'status':'ok','version':'2.0.0','ai':bool(app.config['ANTHROPIC_API_KEY'])})

# ── Boot ───────────────────────────────────────────────────────────────────────
with app.app_context():
    init_db()
    _db = sqlite3.connect(app.config['DATABASE'])
    if not _db.execute("SELECT id FROM companies WHERE email='demo@company.com'").fetchone():
        _db.execute("INSERT INTO companies(id,name,email,password,company,industry) VALUES(?,?,?,?,?,?)",
                    (str(uuid.uuid4()),'Demo HR','demo@company.com',hash_pw('demo1234'),'Demo Corp','Technology'))
        _db.commit()
    _db.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT',5000))
    print(f"\n🚀 ATS Pro v2  →  http://localhost:{port}")
    print(f"   /           Landing page (choose your path)")
    print(f"   /check      Guest resume checker (no login)")
    print(f"   /company    Company dashboard (login required)")
    print(f"   AI: {'Enabled ✓' if app.config['ANTHROPIC_API_KEY'] else 'Demo mode (set ANTHROPIC_API_KEY)'}")
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG','false')=='true')
