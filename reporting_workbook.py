"""Populate the checked-in, designed OOXML template without an Excel service.

Uses only Python's standard library at runtime. Formula caches and native chart
caches are refreshed, so mobile previews do not depend on Excel recalculation.
Only our trusted template contains formulas; all user text is inline string data.
"""
import copy
import math
import re
import zipfile
from datetime import date,datetime,time,timedelta
from pathlib import Path
from xml.etree import ElementTree as E
from reporting_data import SGT

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
CNS='http://schemas.openxmlformats.org/drawingml/2006/chart'
RNS='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
E.register_namespace('',NS)
E.register_namespace('r',RNS)
def tag(n): return '{'+NS+'}'+n
def col(n):
    s=''
    while n:
        n,r=divmod(n-1,26);s=chr(65+r)+s
    return s
def index(s):
    n=0
    for x in s:n=n*26+ord(x)-64
    return n
def addresses(a,b):
    ca,ra=re.fullmatch(r'([A-Z]+)(\d+)',a).groups();cb,rb=re.fullmatch(r'([A-Z]+)(\d+)',b).groups()
    return [f'{col(c)}{r}' for r in range(int(ra),int(rb)+1) for c in range(index(ca),index(cb)+1)]
def serial(value):
    if isinstance(value,datetime):
        value=value.astimezone(SGT).replace(tzinfo=None) if value.tzinfo else value
    else:value=datetime.combine(value,time.min)
    return (value-datetime(1899,12,30)).total_seconds()/86400

class Book:
    def __init__(self,path):
        with zipfile.ZipFile(path) as z:self.parts={n:z.read(n) for n in z.namelist()}
        workbook=E.fromstring(self.parts['xl/workbook.xml'])
        rels=E.fromstring(self.parts['xl/_rels/workbook.xml.rels'])
        targets={e.get('Id'):e.get('Target').lstrip('/') for e in rels}
        self.sheets={};self.paths={};self.cells={};self.memo={};self.visiting=set()
        self.strings=[]
        if 'xl/sharedStrings.xml' in self.parts:
            self.strings=[''.join(e.itertext()) for e in E.fromstring(self.parts['xl/sharedStrings.xml'])]
        for sh in workbook.find(tag('sheets')):
            target=targets[sh.get('{'+RNS+'}id')]
            path=target if target.startswith('xl/') else 'xl/'+target
            name=sh.get('name');root=E.fromstring(self.parts[path])
            self.paths[name]=path;self.sheets[name]=root
            for c in root.iter(tag('c')):self.cells[name,c.get('r')]=c
    def cell(self,sheet,address):
        if (sheet,address) in self.cells:return self.cells[sheet,address]
        root=self.sheets[sheet];data=root.find(tag('sheetData'));rownum=int(re.search(r'\d+',address).group())
        row=next((r for r in data if r.get('r')==str(rownum)),None)
        if row is None:
            row=E.Element(tag('row'),r=str(rownum))
            position=next((i for i,r in enumerate(data) if int(r.get('r'))>rownum),len(data));data.insert(position,row)
        c=E.Element(tag('c'),r=address)
        if sheet=='Caregiver summary' and rownum>228:
            exemplar=self.cells.get((sheet,re.sub(r'\d+','9',address)))
            if exemplar is not None and exemplar.get('s'):c.set('s',exemplar.get('s'))
        if sheet=='AI usage' and rownum>30:
            exemplar=self.cells.get((sheet,re.sub(r'\d+','8',address)))
            if exemplar is not None and exemplar.get('s'):c.set('s',exemplar.get('s'))
        ci=index(re.match('[A-Z]+',address).group())
        position=next((i for i,e in enumerate(row) if index(re.match('[A-Z]+',e.get('r')).group())>ci),len(row));row.insert(position,c)
        self.cells[sheet,address]=c;return c
    def set(self,sheet,address,value):
        c=self.cell(sheet,address)
        for child in list(c):c.remove(child)
        c.attrib.pop('t',None)
        if value is None:return
        if isinstance(value,(date,datetime)):value=serial(value)
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            if not math.isfinite(value):raise ValueError('Non-finite report value')
            E.SubElement(c,tag('v')).text=str(value)
        else:
            c.set('t','inlineStr');node=E.SubElement(E.SubElement(c,tag('is')),tag('t'))
            node.text=''.join(ch for ch in str(value)[:32000] if ord(ch)>=32 or ch in '\n\t\r')
            node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
    def formula(self,sheet,address,formula):
        c=self.cell(sheet,address)
        for child in list(c):c.remove(child)
        c.attrib.pop('t',None)
        E.SubElement(c,tag('f')).text=formula.lstrip('=')
    def row(self,sheet,row,values,start=2):
        for n,v in enumerate(values,start):self.set(sheet,col(n)+str(row),v)
    def value(self,sheet,address):
        key=(sheet,address.replace('$',''))
        if key in self.memo:return self.memo[key]
        if key in self.visiting:raise ValueError('Circular workbook formula')
        self.visiting.add(key)
        c=self.cells.get(key);value=None
        if c is not None:
            f=c.find(tag('f'));v=c.find(tag('v'))
            if f is not None:value=self.evaluate(f.text,sheet)
            elif c.get('t')=='inlineStr':value=''.join(c.find(tag('is')).itertext())
            elif v is not None:
                if c.get('t')=='s':value=self.strings[int(v.text)]
                elif c.get('t')=='str':value=v.text or ''
                else:value=float(v.text) if '.' in v.text or 'e' in v.text.lower() else int(v.text)
        self.visiting.remove(key);self.memo[key]=value;return value
    def evaluate(self,formula,sheet):
        # Parse a strictly limited formula grammar; never execute formula text as Python.
        pattern=r'\s*(\d+(?:\.\d+)?|"(?:[^"]|"")*"|(?:\'(?:[^\']|\'\')+\'|[A-Za-z_][A-Za-z0-9_]*)!\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?|\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?|[A-Z]+|<>|>=|<=|[(),+*/=<>-])'
        tokens=[];offset=0
        while offset<len(formula):
            match=re.match(pattern,formula[offset:])
            if not match:raise ValueError('Unsupported template formula: '+formula)
            tokens.append(match.group(1));offset+=match.end()
        position=0
        def parse(minprec=0):
            nonlocal position
            tok=tokens[position];position+=1
            if tok=='-':node=('neg',parse(4))
            elif tok=='(':
                node=parse();assert tokens[position]==')';position+=1
            elif re.fullmatch('[A-Z]+',tok) and position<len(tokens) and tokens[position]=='(':
                position+=1;args=[]
                if tokens[position]!=')':
                    while True:
                        args.append(parse())
                        if tokens[position]!=',':break
                        position+=1
                assert tokens[position]==')';position+=1;node=('call',tok,args)
            elif tok.startswith('"'):node=('literal',tok[1:-1].replace('""','"'))
            elif re.fullmatch(r'\d+(?:\.\d+)?',tok):node=('literal',float(tok))
            else:node=('ref',tok)
            precedence={'=':1,'<>':1,'>':1,'<':1,'>=':1,'<=':1,'+':2,'-':2,'*':3,'/':3}
            while position<len(tokens) and tokens[position] in precedence and precedence[tokens[position]]>=minprec:
                op=tokens[position];position+=1;node=('op',op,node,parse(precedence[op]+1))
            return node
        tree=parse()
        if position!=len(tokens):raise ValueError('Incomplete template formula')
        def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool)
        def flat(values):
            return [item for value in values for item in (value if isinstance(value,list) else [value])]
        def ev(n):
            kind=n[0]
            if kind=='literal':return n[1]
            if kind=='ref':
                ref=n[1].replace('$','');sh=sheet
                if '!' in ref:
                    sh,ref=ref.split('!');sh=sh.strip("'").replace("''", "'")
                if ':' in ref:return [self.value(sh,a) for a in addresses(*ref.split(':'))]
                return self.value(sh,ref)
            if kind=='neg':return -ev(n[1])
            if kind=='op':
                op=n[1];a,b=ev(n[2]),ev(n[3])
                if op in {'=','<>','<','>','<=','>='}:
                    if a is None:a=''
                    if b is None:b=''
                    if op=='=':return a==b
                    if op=='<>':return a!=b
                    if type(a)!=type(b) and not (numeric(a) and numeric(b)):return False
                    return {'<':lambda:a<b,'>':lambda:a>b,'<=':lambda:a<=b,'>=':lambda:a>=b}[op]()
                a=0 if a in (None,'') else a;b=0 if b in (None,'') else b
                return {'+':lambda:a+b,'-':lambda:a-b,'*':lambda:a*b,'/':lambda:a/b}[op]()
            name,args=n[1:]
            if name=='IF':return ev(args[1]) if ev(args[0]) else ev(args[2])
            values=[ev(a) for a in args];items=flat(values);numbers=[x for x in items if numeric(x)]
            if name=='AND':return all(values)
            if name=='ISNUMBER':return numeric(values[0])
            if name=='COUNT':return len(numbers)
            if name=='COUNTA':return sum(x is not None and x!='' for x in items)
            if name=='SUM':return sum(numbers)
            if name=='MIN':return min(numbers) if numbers else 0
            if name=='AVERAGE':return sum(numbers)/len(numbers) if numbers else None
            if name=='COUNTIFS':
                pairs=list(zip(values[::2],values[1::2]));count=0
                for i in range(len(pairs[0][0])):
                    matches=[]
                    for cells,criterion in pairs:
                        value=cells[i]
                        if isinstance(criterion,str) and criterion.startswith('>'):
                            matches.append(numeric(value) and value>float(criterion[1:]))
                        else:matches.append(value==criterion)
                    count+=all(matches)
                return count
            raise ValueError('Unsupported template function '+name)
        return ev(tree)
    def save(self,path):
        output_path=path
        self.memo.clear()
        for (sheet,address),cell in list(self.cells.items()):
            if cell.find(tag('f')) is None:continue
            result=self.value(sheet,address)
            old=cell.find(tag('v'))
            if old is not None:cell.remove(old)
            cell.attrib.pop('t',None)
            if isinstance(result,str):cell.set('t','str')
            E.SubElement(cell,tag('v')).text='' if result is None else str(result)
        for sheet,root in self.sheets.items():
            cells=[a for s,a in self.cells if s==sheet]
            maximum=max(int(re.search(r'\d+',a).group()) for a in cells)
            dim=root.find(tag('dimension'))
            if dim is not None:dim.set('ref',f'A1:Z{maximum}')
            self.parts[self.paths[sheet]]=E.tostring(root,encoding='utf-8',xml_declaration=True)
        for path,data in list(self.parts.items()):
            if not re.fullmatch(r'xl/(?:drawings/)?charts/chart\d+\.xml',path):continue
            root=E.fromstring(data)
            chart_numbers=[];fractional=False
            for reference in list(root.iter('{'+CNS+'}numRef'))+list(root.iter('{'+CNS+'}strRef')):
                f=reference.find('{'+CNS+'}f')
                if f is None:continue
                formula=f.text
                sh,ref=formula.rsplit('!',1);sh=sh.strip("'").replace("''", "'");ref=ref.replace('$','')
                values=[self.value(sh,a) for a in addresses(*(ref.split(':') if ':' in ref else [ref,ref]))]
                if reference.tag.endswith('numRef'):
                    chart_numbers.extend(v for v in values if isinstance(v,(int,float)))
                    fractional=fractional or sh=='Activity'
                cache_name='numCache' if reference.tag.endswith('numRef') else 'strCache'
                old=reference.find('{'+CNS+'}'+cache_name)
                if old is not None:reference.remove(old)
                cache=E.SubElement(reference,'{'+CNS+'}'+cache_name)
                if cache_name=='numCache':E.SubElement(cache,'{'+CNS+'}formatCode').text='General'
                E.SubElement(cache,'{'+CNS+'}ptCount',val=str(len(values)))
                for i,value in enumerate(values):
                    if value is None or value=='':continue
                    if cache_name=='numCache' and not isinstance(value,(int,float)):continue
                    pt=E.SubElement(cache,'{'+CNS+'}pt',idx=str(i));E.SubElement(pt,'{'+CNS+'}v').text=str(value)
            # Honest zero baselines and distinct, readable axis labels at small scales.
            maximum=max(chart_numbers or [0])
            target=maximum/5 if maximum>0 else 1
            scale=10**math.floor(math.log10(target))
            step=next((v*scale for v in [1,2,5,10] if v*scale>=target),10*scale)
            if not fractional:step=max(1,step)
            for axis in root.iter('{'+CNS+'}valAx'):
                scaling=axis.find('{'+CNS+'}scaling')
                if scaling is not None:
                    old=scaling.find('{'+CNS+'}min')
                    if old is None:old=E.SubElement(scaling,'{'+CNS+'}min')
                    old.set('val','0')
                unit=axis.find('{'+CNS+'}majorUnit')
                if unit is None:unit=E.SubElement(axis,'{'+CNS+'}majorUnit')
                unit.set('val',str(step))
                fmt=axis.find('{'+CNS+'}numFmt')
                if fmt is not None:fmt.set('formatCode','0.0' if fractional else '#,##0')
            self.parts[path]=E.tostring(root,encoding='utf-8',xml_declaration=True)
        workbook=E.fromstring(self.parts['xl/workbook.xml']);calc=workbook.find(tag('calcPr'))
        if calc is None:calc=E.SubElement(workbook,tag('calcPr'))
        calc.set('fullCalcOnLoad','1');calc.set('forceFullCalc','1')
        self.parts['xl/workbook.xml']=E.tostring(workbook,encoding='utf-8',xml_declaration=True)
        with zipfile.ZipFile(output_path,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,data in self.parts.items():z.writestr(name,data)

def build_report(data,path):
    book=Book(Path(__file__).parent/'report_templates'/'CareConnectStatistics_Template.xlsx')
    start,end=data['start'],data['end'];days=(end-start).days+1
    book.row('Controls',8,['Report start',start]);book.set('Controls','C9',end);book.set('Controls','C10',data['generated'])
    book.set('Dashboard','B4',f'{start:%d %b %Y} to {end:%d %b %Y}. Snapshot generated in Singapore time.')
    if data.get('synthetic'):book.set('Dashboard','B4',f'SYNTHETIC TEST DATA. {start:%d %b %Y} to {end:%d %b %Y}.')
    book.set('Dashboard','G34',f"Tracking began {data['coverage'].astimezone(SGT):%d %b %Y %H:%M} SGT. Earlier periods are incomplete.")
    for sheet in ['Services','Buddy programme','Messages & costs','Sample data']:
        book.set(sheet,'B4','Recorded figures for the requested period. See Definitions for coverage and counting rules.')
    for row,period in zip([7,8],data['periods']):book.row('Sample data',row,period)
    source_keys=['active','new','ai','resource',None,None,'requests','request_accepted','request_declined','request_pending','app_start','application_cohort','application_approved','application_rejected','application_pending','profile_accepted','profile_edited','profile_rejected','received','outgoing','delivered','failed','read']
    for offset in range(days*2):
        d=data['previous']+timedelta(days=offset);counts=data['daily'][d]
        counts['searches']=counts['search_preview']+counts['search_no_preview']
        current_start=44 if days==31 else 43
        row=13+offset if offset<days else current_start+offset-days
        values=[d,d.strftime('%d %b')]+[counts[k] if k else None for k in source_keys]
        values[6]=counts['searches'];values[7]=counts['search_preview']
        # Do not misrepresent uncovered history as complete zeroes.
        if d<data['coverage'].astimezone(SGT).date():
            for i in [2,3,6,7,17,18,19,21,22,23,24]:values[i]=None
        book.row('Sample data',row,values)
        if row==74:
            for column in range(2,27):
                cell=book.cell('Sample data',f'{col(column)}74');source=book.cell('Sample data',f'{col(column)}73')
                if source.get('s'):cell.set('s',source.get('s'))
    if days==31:
        # Both periods have 31 days. Move the current block down one row instead
        # of overwriting the final day of the preceding comparison period.
        pattern=r"('Sample data'!)(\$?[A-Z]+\$?)(\d+)(?::(\$?[A-Z]+\$?)(\d+))?"
        def shift(match):
            prefix,column,first,last_column,last=match.groups();first=int(first)
            if last is not None:
                last=int(last)
                if first==13 and last==42:return f'{prefix}{column}13:{last_column}43'
                if first==43 and last==73:return f'{prefix}{column}44:{last_column}74'
            elif 43<=first<=73:return f'{prefix}{column}{first+1}'
            return match.group(0)
        for cell in book.cells.values():
            formula=cell.find(tag('f'))
            if formula is not None:formula.text=re.sub(pattern,shift,formula.text)
        for name,raw in list(book.parts.items()):
            if name.startswith('xl/tables/') and name.endswith('.xml'):
                root=E.fromstring(raw)
                if root.get('ref')=='B12:Z73':
                    root.set('ref','B12:Z74');af=root.find(tag('autoFilter'))
                    if af is not None:af.set('ref','B12:Z74')
                    book.parts[name]=E.tostring(root,encoding='utf-8',xml_declaration=True)
    for row,heat in [(81,data['heat']),(92,data['buddy_heat'])]:
        for i,values in enumerate(heat):book.row('Sample data',row+i,values,3)
    for i in range(4):book.set('Sample data',f'C{122+i}',data['categories'][str(i+1)])
    for i,text in enumerate(data['warnings'],8):
        book.set('Definitions',f'B{i}',text)
    book.set('Services','B30','Feature openings count repeated visits. Consent and profile decisions count recorded actions.')
    book.set('Services','B32','Resource content remains subject to RDSS approval.')
    book.set('Activity','B4','Observed bot activity in SGT. Buddy heatmap uses currently approved buddies; it does not show online presence.')
    book.set('Controls','E12','AI rates are editable per model on AI usage. Blank rates mean unknown.')
    book.set('Controls','E26','This is a generated snapshot, not a live connection to the database.')
    book.set('Controls','E29','Request another date range through the WhatsApp administrator menu.')
    book.set('Controls','E41','The report generator supplies the requested dates and matching stored records.')
    book.set('Definitions','B4','Definitions and coverage for this generated snapshot.')
    book.set('Messages & costs','B9','Accepted by WhatsApp')
    book.set('Messages & costs','B13','Unconfirmed send attempts')
    book.set('Messages & costs','C13',sum(v['unknown_sends'] for d,v in data['daily'].items() if d>=start))
    book.set('Controls','E19','Enter hosting/database charges allocated to this reporting period, in USD.')
    book.set('Controls','B19','Web service / selected period');book.set('Controls','B20','Database / selected period')
    # Real per-search outcomes, not subtraction of unrelated feature events.
    searches=sum(data['daily'][d]['search_no_preview'] for d in data['daily'] if d>=start)
    book.set('Buddy programme','C29',searches)
    total=max(228,8+len(data['caregivers']))
    for row,values in enumerate(data['caregivers'],9):
        book.row('Caregiver summary',row,values)
        # Fitted row height for approved free text, including scripts using wide glyphs.
        import unicodedata
        lines=max([1]+[math.ceil(sum(2 if unicodedata.east_asian_width(c) in {'W','F'} else 1 for c in str(values[i] or ''))/width) for i,width in [(3,40),(4,40),(5,28)]])
        cell=book.cell('Caregiver summary',f'B{row}')
        xml_row=next(r for r in book.sheets['Caregiver summary'].find(tag('sheetData')) if r.get('r')==str(row))
        xml_row.set('ht',str(max(34,16*lines+8)));xml_row.set('customHeight','1')
    if not data['caregivers']:
        for address in ['C6','G6','J6','P6']:book.set('Caregiver summary',address,0)
    book.set('Caregiver summary','B4','Individual rows include only current reporting permission. Other users appear in aggregate statistics only.')
    for row in range(9,229):
        if row>=9+len(data['caregivers']):book.set('Caregiver summary',f'O{row}',None)
    for address in ['C6','G6','J6','P6']:
        cell=book.cell('Caregiver summary',address);formula=cell.find(tag('f'))
        if formula is not None:formula.text=formula.text.replace('228',str(total))
    # Extend the native caregiver table/filter without truncating large populations.
    for name,raw in list(book.parts.items()):
        if name.startswith('xl/tables/') and name.endswith('.xml'):
            root=E.fromstring(raw)
            if root.get('ref')=='B8:S228':
                root.set('ref',f'B8:S{total}')
                af=root.find(tag('autoFilter'))
                if af is not None:af.set('ref',f'B8:S{total}')
                book.parts[name]=E.tostring(root,encoding='utf-8',xml_declaration=True)
    # Feature summary retains the design; the full, expandable ledger owns model costs.
    groups={f:f for f in ['AI Chat','Translation','Menu routing','Profile extraction','Language detection']}
    groups.update({f:'Menu routing' for f in ['Matching onboarding','Matching preferences','Confirmation']})
    ai_groups={};unknown=0
    for feature,model,outcome,inp,cached,out,tier,stamp in data['ai']:
        key=(feature,model,tier or 'default')
        row=ai_groups.setdefault(key,[0,0,0,0,0])
        row[0]+=1
        if outcome!='completed' or None in (inp,cached,out):row[4]+=1;unknown+=1
        for j,value in enumerate([inp,cached,out],1):
            if value is not None:row[j]+=value
    ai_end=max(8,7+len(ai_groups))
    for i,((feature,model,tier),values) in enumerate(sorted(ai_groups.items()),8):
        requests,inp,cached,out,missing=values
        book.row('AI usage',i,[feature,model,tier,requests,inp,cached,out,missing,None,None,None,None])
        book.formula('AI usage',f'M{i}',f'IF(AND(I{i}=0,COUNT(J{i}:L{i})=3,MIN(J{i}:L{i})>=0),((F{i}-G{i})*J{i}+G{i}*K{i}+H{i}*L{i})/1000000,"")')
    for name,raw in list(book.parts.items()):
        if name.startswith('xl/tables/') and name.endswith('.xml'):
            root=E.fromstring(raw)
            if root.get('name')=='AiUsageLedger':
                root.set('ref',f'B7:M{max(30,ai_end)}')
                af=root.find(tag('autoFilter'))
                if af is not None:af.set('ref',root.get('ref'))
                book.parts[name]=E.tostring(root,encoding='utf-8',xml_declaration=True)
    book.set('AI usage','B4','Provider-reported tokens. Fill amber rates in USD per million tokens. Unknown calls keep cost unavailable.')
    book.set('AI usage','F7','Known input tokens')
    book.set('AI usage','G7','Known cached input')
    book.set('AI usage','H7','Known output tokens')
    for index_,feature in enumerate(['AI Chat','Translation','Menu routing','Profile extraction','Language detection']):
        items=[(key,v) for key,v in ai_groups.items() if groups[key[0]]==feature]
        summary=[sum(v[j] for _,v in items) for j in range(4)]
        if any(v[4] for _,v in items):summary[1:]=[None,None,None]
        models=sorted({key[1] for key,_ in items})
        book.row('Sample data',105+index_,[', '.join(models) or 'No calls',*summary],3)
        matching=[i for i,(key,_) in enumerate(sorted(ai_groups.items()),8) if groups[key[0]]==feature]
        if matching:
            refs=','.join(f"'AI usage'!M{i}" for i in matching)
            book.formula('Messages & costs',f'G{20+index_}',f'IF(COUNT({refs})={len(matching)},SUM({refs}),"")')
        else:book.set('Messages & costs',f'G{20+index_}',0)
    book.set('Messages & costs','B22','Routing & onboarding')
    book.set('AI usage','B6',f'{unknown} calls have incomplete usage. Failed calls may have unknown provider charges. Rates must match model, tier and date.')
    book.set('Messages & costs','B17','All AI features; model and tier details on AI usage')
    if not ai_groups:book.set('AI usage','B8','No API calls recorded in this period')
    # Billing categories must be confirmed by callbacks. Missing classification stays unknown.
    by_message={}
    for identifier,category,billable,pricing_model in data['billing']:
        item=by_message.setdefault(identifier,{'category':set(),'billable':set()})
        if category:item['category'].add(category)
        if billable is not None and pricing_model=='PMP':item['billable'].add(billable)
    known_messages=0
    bill_counts={key:0 for key in ['service','utility','marketing','authentication']}
    for item in by_message.values():
        if len(item['category'])==1 and len(item['billable'])==1:
            known_messages+=1
            if next(iter(item['billable'])):bill_counts[next(iter(item['category']))]+=1
    delivered=sum(data['daily'][d]['delivered'] for d in data['daily'] if d>=start)
    unknown_billing=max(0,delivered-known_messages)
    for i,key in enumerate(['service','utility','marketing','authentication']):
        book.set('Sample data',f'C{116+i}',bill_counts[key])
        row=30+i
        book.formula('Messages & costs',f'E{row}',f'IF(ISNUMBER(C{row}),IF(C{row}=0,0,IF(AND(ISNUMBER(D{row}),D{row}>=0),C{row}*D{row},"")),"")')
    book.set('Messages & costs','B36','Unclassified delivered')
    book.set('Messages & costs','C36',unknown_billing)
    book.formula('Messages & costs','E34','IF(AND(C36=0,COUNT(E30:E33)=4),SUM(E30:E33),"")')
    book.set('Messages & costs','B28','Confirmed billable messages by category')
    book.set('Sample data','B113','Confirmed billable messages. Free and unknown classifications are not billable counts.')
    book.set('Messages & costs','B35','Known categories are shown. Unclassified delivery or missing rates keep the total blank.')
    # No delivered messages means known zero charges, irrespective of rate placeholders.
    if delivered==0:
        for row in range(30,34):book.set('Messages & costs',f'E{row}',0)
    # Bind the native daily chart to the actual requested day count, including
    # its cached points. A 7-day report must not leave 24 empty date slots.
    for part,raw in list(book.parts.items()):
        if not re.fullmatch(r'xl/(?:drawings/)?charts/chart\d+\.xml',part):continue
        root=E.fromstring(raw);changed=False
        for reference in root.iter('{'+CNS+'}f'):
            if reference.text and "'Sample data'!" in reference.text:
                replacement=re.sub(r'(\$?[BCD]\$?131:\$?[BCD]\$?)161$',lambda m:m.group(1)+str(130+days),reference.text)
                if replacement!=reference.text:reference.text=replacement;changed=True
        if changed:book.parts[part]=E.tostring(root,encoding='utf-8',xml_declaration=True)
    book.save(path)
    return path
