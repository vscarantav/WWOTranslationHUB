import os
import re
import pandas as pd
from datetime import datetime
import xlsxwriter

class DashboardGenerator:
    def __init__(self, log_filepath: str, hub_dir: str, default_target: str):
        self.log_filepath = log_filepath
        self.hub_dir = hub_dir
        self.default_target = default_target

    def generate(self, _log_func):
        msg = "Generating Excel Analytics Dashboard..."
        print(f"\n[DashboardGenerator] {msg}")
        _log_func(msg)
        
        data = []
        if os.path.exists(self.log_filepath):
            session_target = self.default_target
            with open(self.log_filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    session_match = re.match(r'--- New Session \(Target: (.*?)\) ---', line)
                    if session_match:
                        session_target = session_match.group(1)
                        continue
                        
                    log_match = re.match(r'\[(.*?)\] (.*)', line)
                    if log_match:
                        ts_str, message = log_match.group(1), log_match.group(2)
                        try:
                            timestamp = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                        except:
                            timestamp = None
                        
                        bot_name = 'System'
                        bot_match = re.match(r'^\[(.*?)\]\s*(.*)', message)
                        if bot_match:
                            bot_name = bot_match.group(1)
                            message = bot_match.group(2)

                        entry = {
                            'Timestamp': timestamp,
                            'Date': timestamp.date() if timestamp else None,
                            'Hour': timestamp.hour if timestamp else None,
                            'Target Language': session_target,
                            'Event Type': 'Log',
                            'Bot': bot_name,
                            'File Path': '',
                            'File Name': '',
                            'Status': 'Info',
                            'Message': message
                        }
                        
                        if message.startswith('Delegating '):
                            m = re.match(r'Delegating (.*) to (.*)', message)
                            if m:
                                entry['Event Type'] = 'Delegation'
                                entry['Status'] = 'Success'
                                entry['File Path'] = m.group(1)
                                entry['Bot'] = m.group(2)
                                entry['File Name'] = entry['File Path'].split('/')[-1]
                        elif message.startswith('Skipping ignored'):
                            entry['Event Type'] = 'Skipped'
                            entry['Status'] = 'Warning'
                            entry['File Path'] = message.replace('Skipping ignored system file: ', '')
                            entry['File Name'] = entry['File Path'].split('/')[-1]
                        elif message.startswith('Skipping already translated'):
                            entry['Event Type'] = 'Skipped (Already Translated)'
                            entry['Status'] = 'Info'
                            entry['File Path'] = message.replace('Skipping already translated file: ', '')
                            entry['File Name'] = entry['File Path'].split('/')[-1]
                        elif 'Skipping AuditorBot' in message:
                            entry['Event Type'] = 'Skipped (Size Limit)'
                            entry['Status'] = 'Warning'
                        elif message.startswith('CourseInfo: '):
                            entry['Event Type'] = 'Course Info'
                            entry['Message'] = message.replace('CourseInfo: ', '')
                            entry['Status'] = 'Info'
                        elif message.startswith('ExtLink: '):
                            entry['Event Type'] = 'External Link'
                            entry['Bot'] = 'LinkBot'
                            parts = message.replace('ExtLink: ', '').split(',', 2)
                            if len(parts) == 3:
                                entry['File Name'] = parts[0]
                                entry['Message'] = f"{parts[1]} | {parts[2]}"
                            entry['Status'] = 'Info'
                        elif message.startswith('GoogleLinkStripped: '):
                            entry['Event Type'] = 'Google Link Stripped'
                            entry['Bot'] = 'LinkBot'
                            parts = message.replace('GoogleLinkStripped: ', '').split(',', 2)
                            if len(parts) == 3:
                                entry['File Name'] = parts[0]
                                entry['Message'] = f"{parts[1]} | {parts[2]}"
                            entry['Status'] = 'Success'
                        elif message.startswith('CommentedLink: ') or message.startswith('SkippedLinkWithComment: '):
                            entry['Event Type'] = 'Commented Link'
                            entry['Bot'] = 'LinkBot'
                            if message.startswith('CommentedLink: '):
                                raw_data = message.replace('CommentedLink: ', '')
                                entry['Status'] = 'Success'
                            else:
                                raw_data = message.replace('SkippedLinkWithComment: ', '')
                                entry['Status'] = 'Info'
                            parts = raw_data.split(',', 2)
                            if len(parts) == 3:
                                entry['File Name'] = parts[0]
                                entry['Message'] = f"{parts[1]} | {parts[2]}"
                        elif message.startswith('SkippedLink: '):
                            entry['Event Type'] = 'Skipped Link'
                            entry['Bot'] = 'LinkBot'
                            parts = message.replace('SkippedLink: ', '').split(',', 1)
                            if len(parts) == 2:
                                entry['File Name'] = parts[0]
                                entry['Message'] = parts[1]
                            entry['Status'] = 'Info'
                        elif message.startswith('FileTypeCount: '):
                            entry['Event Type'] = 'File Type Count'
                            parts = message.replace('FileTypeCount: ', '').split('|', 1)
                            if len(parts) == 2:
                                entry['File Name'] = parts[0]
                                entry['Message'] = parts[1]
                            entry['Status'] = 'Info'
                        elif message.startswith('TranslatedPage: '):
                            entry['Event Type'] = 'Translated Page'
                            entry['Status'] = 'Success'
                            parts = message.replace('TranslatedPage: ', '').split(' | ', 1)
                            if len(parts) == 2:
                                entry['Message'] = parts[0]
                                entry['File Path'] = parts[1]
                                entry['File Name'] = parts[1].split('/')[-1]
                            else:
                                entry['Message'] = message.replace('TranslatedPage: ', '')
                        elif 'error' in message.lower() or 'exception' in message.lower():
                            entry['Status'] = 'Error'
                            entry['Event Type'] = 'Error'
                        elif 'Found references' in message or 'Found ' in message:
                            entry['Status'] = 'Success'
                            entry['Event Type'] = 'Extraction Found'
                            
                        data.append(entry)

        if not data:
            _log_func("[DashboardGenerator] No data to generate dashboard.")
            return
            
        df = pd.DataFrame(data)
        
        course_name = "Course"
        course_code = "UNKNOWN"
        course_info_rows = df[df['Event Type'] == 'Course Info']
        if not course_info_rows.empty:
            msg = course_info_rows.iloc[-1]['Message']
            parts = msg.split('|')
            if len(parts) >= 2:
                course_name = parts[0].strip()
                course_code = parts[1].strip()
                
        safe_course_name = "".join([c for c in course_name if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        if not safe_course_name:
            safe_course_name = "Course"
            
        excel_filename = f"{safe_course_name} Translation Report.xlsx"
        reports_dir = os.path.join(self.hub_dir, "Reports")
        os.makedirs(reports_dir, exist_ok=True)
        excel_path = os.path.join(reports_dir, excel_filename)
        workbook = xlsxwriter.Workbook(excel_path)

        # Custom Formats
        title_fmt = workbook.add_format({'bold': True, 'font_size': 26, 'font_color': '#2C3E50', 'bg_color': '#ECF0F1', 'align': 'center', 'valign': 'vcenter'})
        subtitle_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#7F8C8D', 'bg_color': '#ECF0F1', 'align': 'center'})
        header_fmt = workbook.add_format({'bold': True, 'font_color': 'white', 'bg_color': '#34495E', 'border': 1, 'align': 'center'})
        cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'border': 1, 'valign': 'vcenter'})
        kpi_header_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'font_color': 'white', 'bg_color': '#2980B9', 'align': 'center', 'border': 1})
        kpi_val_fmt = workbook.add_format({'bold': True, 'font_size': 20, 'font_color': '#2C3E50', 'align': 'center', 'border': 1, 'bg_color': '#D6EAF8'})
        success_fmt = workbook.add_format({'bg_color': '#C8E6C9', 'font_color': '#1B5E20'})
        warning_fmt = workbook.add_format({'bg_color': '#FFE082', 'font_color': '#E65100'})
        error_fmt = workbook.add_format({'bg_color': '#FFCDD2', 'font_color': '#B71C1C'})

        # SHEET 1: Dashboard
        dash = workbook.add_worksheet('Dashboard')
        dash.hide_gridlines(2)
        dash.set_column('A:A', 2)
        dash.set_column('B:G', 20)
        dash.set_row(1, 40)
        dash.merge_range('B2:G2', 'Course Translation Hub Analytics', title_fmt)
        dash.merge_range('B3:G3', 'Automated Bot Performance & Log Analysis', subtitle_fmt)
        
        dash.merge_range('B4:G4', f'Course: {course_name} ({course_code})', workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'}))
        
        dash.write('B5', 'Total Log Events', kpi_header_fmt)
        dash.write_formula('B6', '=COUNTA(\'Raw Logs\'!A:A)-1', kpi_val_fmt)
        dash.write('D5', 'Successful Operations', kpi_header_fmt)
        dash.write_formula('D6', '=COUNTIF(\'Raw Logs\'!I:I, "Success")', kpi_val_fmt)
        dash.write('F5', 'Errors / Warnings', kpi_header_fmt)
        dash.write_formula('F6', '=COUNTIF(\'Raw Logs\'!I:I, "Error") + COUNTIF(\'Raw Logs\'!I:I, "Warning")', kpi_val_fmt)
        
        dash.write('B8', 'Filter Bot Activity:', workbook.add_format({'bold': True, 'font_size': 12}))
        bots_list = list(df['Bot'].dropna().unique())
        if bots_list:
            dash.data_validation('C8', {'validate': 'list', 'source': bots_list})
            dash.write('C8', bots_list[0], workbook.add_format({'border': 1, 'bg_color': '#FFFFE0'}))
        dash.write('B9', 'Events for Selected Bot:', workbook.add_format({'bold': True}))
        dash.write_formula('C9', '=COUNTIF(\'Raw Logs\'!F:F, C8)', workbook.add_format({'bold': True, 'font_size': 14, 'color': '#2980B9'}))

        dash.write('I5', 'Skipped Files', header_fmt)
        dash.set_column('I:I', 40)
        skipped_df = df[df['Event Type'].str.contains('Skipped', na=False)]
        row_idx = 5
        for idx, row in skipped_df.iterrows():
            dash.write(row_idx, 8, str(row['File Name']), cell_fmt)
            row_idx += 1
            
        dash.write('K5', 'File Extension', header_fmt)
        dash.write('L5', 'Total Count', header_fmt)
        dash.set_column('K:L', 15)
        
        file_counts_rows = df[df['Event Type'] == 'File Type Count']
        row_idx = 5
        for idx, row in file_counts_rows.iterrows():
            dash.write(row_idx, 10, str(row['File Name']), cell_fmt)
            dash.write(row_idx, 11, int(row['Message']), cell_fmt)
            row_idx += 1

        # SHEET 2: Bot Statistics
        bot_stats = workbook.add_worksheet('Bot Analysis')
        bot_stats.set_column('A:E', 20)
        bot_stats.write_row('A1', ['Bot Name', 'Total Events', 'Successes', 'Warnings', 'Errors'], header_fmt)
        
        row_idx = 1
        for bot in bots_list:
            bot_stats.write(row_idx, 0, bot, cell_fmt)
            bot_stats.write_formula(row_idx, 1, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}")', cell_fmt)
            bot_stats.write_formula(row_idx, 2, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}", \'Raw Logs\'!I:I, "Success")', cell_fmt)
            bot_stats.write_formula(row_idx, 3, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}", \'Raw Logs\'!I:I, "Warning")', cell_fmt)
            bot_stats.write_formula(row_idx, 4, f'=COUNTIFS(\'Raw Logs\'!F:F, "{bot}", \'Raw Logs\'!I:I, "Error")', cell_fmt)
            row_idx += 1
            
        bot_chart = workbook.add_chart({'type': 'column', 'subtype': 'stacked'})
        bot_chart.add_series({
            'name': 'Successes',
            'categories': ['Bot Analysis', 1, 0, row_idx-1, 0],
            'values': ['Bot Analysis', 1, 2, row_idx-1, 2],
            'fill': {'color': '#4CAF50'}
        })
        bot_chart.add_series({
            'name': 'Warnings',
            'categories': ['Bot Analysis', 1, 0, row_idx-1, 0],
            'values': ['Bot Analysis', 1, 3, row_idx-1, 3],
            'fill': {'color': '#FFC107'}
        })
        bot_chart.add_series({
            'name': 'Errors',
            'categories': ['Bot Analysis', 1, 0, row_idx-1, 0],
            'values': ['Bot Analysis', 1, 4, row_idx-1, 4],
            'fill': {'color': '#F44336'}
        })
        bot_chart.set_title({'name': 'Bot Reliability Breakdown'})
        bot_stats.insert_chart('A10', bot_chart, {'x_scale': 1.5, 'y_scale': 1.5})

        # SHEET 3: Raw Logs
        logs_sheet = workbook.add_worksheet('Raw Logs')
        logs_sheet.set_tab_color('#95A5A6')
        
        columns = list(df.columns)
        logs_sheet.write_row('A1', columns, header_fmt)
        
        for r_num, row_data in df.iterrows():
            for c_num, val in enumerate(row_data):
                if pd.isna(val):
                    val = ''
                if columns[c_num] == 'Timestamp' and val != '':
                    logs_sheet.write_datetime(r_num+1, c_num, val, date_fmt)
                else:
                    logs_sheet.write(r_num+1, c_num, val, cell_fmt)
                    
        logs_sheet.set_column('A:A', 20)
        logs_sheet.set_column('B:D', 12)
        logs_sheet.set_column('E:F', 20)
        logs_sheet.set_column('G:H', 30)
        logs_sheet.set_column('I:I', 15)
        logs_sheet.set_column('J:J', 80)
        logs_sheet.autofilter(0, 0, len(df), len(columns)-1)
        
        logs_sheet.conditional_format(1, 8, len(df), 8, {'type': 'cell', 'criteria': '==', 'value': '"Success"', 'format': success_fmt})
        logs_sheet.conditional_format(1, 8, len(df), 8, {'type': 'cell', 'criteria': '==', 'value': '"Warning"', 'format': warning_fmt})
        logs_sheet.conditional_format(1, 8, len(df), 8, {'type': 'cell', 'criteria': '==', 'value': '"Error"', 'format': error_fmt})

        # SHEET 4: Translated Pages
        translated_pages_df = df[df['Event Type'] == 'Translated Page'].copy()
        
        if not translated_pages_df.empty:
            translated_pages_df = translated_pages_df.drop_duplicates(subset=['Message', 'File Path'])
            
            title_counts = translated_pages_df['Message'].value_counts()
            translated_pages_df['Duplicate Flag'] = translated_pages_df['Message'].apply(
                lambda x: 'Duplicate Name (FIX EN Course)' if title_counts.get(x, 0) > 1 else ''
            )
            
            pages_sheet = workbook.add_worksheet('Translated Pages')
            pages_sheet.set_column('A:A', 60)
            pages_sheet.set_column('B:B', 20)
            
            pages_sheet.write('A1', 'Page Name', header_fmt)
            pages_sheet.write('B1', 'Flag', header_fmt)
            
            r_idx = 1
            for idx, row in translated_pages_df.iterrows():
                pages_sheet.write(r_idx, 0, str(row['Message']), cell_fmt)
                flag = str(row['Duplicate Flag'])
                if flag:
                    pages_sheet.write(r_idx, 1, flag, warning_fmt)
                else:
                    pages_sheet.write(r_idx, 1, '', cell_fmt)
                r_idx += 1

        # SHEET 5: Link Actions (Consolidated)
        action_links_df = df[df['Event Type'].isin(['Google Link Stripped', 'Skipped Link', 'Commented Link'])].copy()
        
        if not action_links_df.empty:
            action_sheet = workbook.add_worksheet('Link Actions')
            action_sheet.set_column('A:A', 25)
            action_sheet.set_column('B:B', 30)
            action_sheet.set_column('C:C', 60)
            action_sheet.set_column('D:D', 60)
            action_sheet.set_column('E:E', 40)
            
            action_sheet.write('A1', 'Event Type', header_fmt)
            action_sheet.write('B1', 'Page Name', header_fmt)
            action_sheet.write('C1', 'Original URL', header_fmt)
            action_sheet.write('D1', 'Clean URL', header_fmt)
            action_sheet.write('E1', 'Notes / Comments', header_fmt)
            
            r_idx = 1
            for idx, row in action_links_df.iterrows():
                event_type = str(row['Event Type'])
                loc = str(row['File Name'])
                msg_val = str(row['Message'])
                
                orig_url = ""
                clean_url = ""
                notes = ""
                
                if event_type == 'Google Link Stripped':
                    parts = msg_val.split(' | ', 1)
                    orig_url = parts[0] if len(parts) > 0 else ""
                    clean_url = parts[1] if len(parts) > 1 else ""
                    notes = "FIX EN Course"
                elif event_type == 'Skipped Link':
                    orig_url = msg_val
                elif event_type == 'Commented Link':
                    parts = msg_val.split(' | ', 1)
                    orig_url = parts[0] if len(parts) > 0 else ""
                    notes = parts[1] if len(parts) > 1 else ""
                    
                action_sheet.write(r_idx, 0, event_type, cell_fmt)
                action_sheet.write(r_idx, 1, loc, cell_fmt)
                action_sheet.write(r_idx, 2, orig_url, cell_fmt)
                action_sheet.write(r_idx, 3, clean_url, cell_fmt)
                
                if notes == "FIX EN Course":
                    action_sheet.write(r_idx, 4, notes, warning_fmt)
                else:
                    action_sheet.write(r_idx, 4, notes, cell_fmt)
                    
                r_idx += 1

        workbook.close()
        msg_success = f"Excel successfully created: {excel_path}"
        print(f"[DashboardGenerator] {msg_success}")
        _log_func(msg_success)
