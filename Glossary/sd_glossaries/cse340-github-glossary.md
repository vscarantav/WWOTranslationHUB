<!-- prettier-ignore -->
# CSE 340 GitHub Course Glossary

| English Term | PT-BR Translation | Context |
| --- | --- | --- |
| Absolute Path | Caminho Absoluto | File path that gives the complete location of a file or directory from the system root. |
| Access Control | Controle de Acesso | Security practice used to decide which users can reach protected application features. |
| Admin Account | Conta de Administrador | User account with elevated permissions for managing restricted parts of the course project. |
| Admin Role | Papel de Administrador | Role used in authorization checks to allow access to admin-only routes and options. |
| AI Policy | Política de IA | Course rule set describing acceptable and unacceptable use of AI tools in assignments and quizzes. |
| Application | Aplicação | The Node.js and Express web project students build throughout the course. |
| Array of Objects | Array de Objetos | Common data shape returned from model functions and passed to EJS templates for display. |
| Assignment | Atividade | Weekly deliverable where students implement and submit application features. |
| Authentication | Autenticação | Process of verifying a user's identity, usually through login credentials. |
| Authorization | Autorização | Process of deciding what an authenticated user is allowed to access or do. |
| bcrypt | bcrypt | Password hashing package used to store passwords securely during user registration and login. |
| Body Parser | Analisador do Corpo da Requisição | Middleware that makes submitted POST form data available in the request object. |
| Browser | Navegador | Client application that sends HTTP requests and receives rendered HTML responses. |
| Business Etiquette | Etiqueta Profissional | Expected respectful behavior for team meetings, communication, and collaboration. |
| Callback Function | Função de Callback | Function passed to another function, often used in route handlers and middleware. |
| Category | Categoria | Course project entity used to group service projects. |
| Client | Cliente | Browser or user-side software that sends requests to the server. |
| Client Error | Erro do Cliente | HTTP 4xx status category indicating a problem with the request made by the client. |
| Client-Side Access Control | Controle de Acesso no Lado do Cliente | UI-level hiding or showing of options, which must not be trusted as real security. |
| Client-Side Validation | Validação no Lado do Cliente | Browser-based form checking that gives immediate feedback before data is submitted. |
| Code Organization | Organização de Código | Practice of separating routes, controllers, models, views, and configuration into clear files. |
| Code Review | Revisão de Código | Process of examining code for correctness, readability, security, and alignment with requirements. |
| Commit | Commit | Git action that records a snapshot of project changes in the repository history. |
| Configuration Order | Ordem de Configuração | Sequence in which Express settings and middleware are added, which affects how requests are processed. |
| Connection String | String de Conexão | Database connection value containing host, credentials, database name, and other connection details. |
| Controller | Controlador | MVC component that receives requests, coordinates model and view work, and sends responses. |
| Cookie | Cookie | Small value stored by the browser, commonly used to carry a session ID between requests. |
| Course Project | Projeto do Curso | Web backend application built incrementally across the course. |
| CSS | CSS | Styling language used to make the rendered web pages look professional. |
| Dashboard | Painel | Protected page shown after login to provide authenticated user functionality. |
| Data Passing | Passagem de Dados | Supplying dynamic values from a route or controller to an EJS template during rendering. |
| Data Retrieval | Recuperação de Dados | Reading records from the database through SQL queries and model functions. |
| Database | Banco de Dados | Persistent storage system used by the project for organizations, projects, categories, users, and roles. |
| Database Credentials | Credenciais do Banco de Dados | Username, password, and connection details that should be stored outside source code. |
| Database Normalization | Normalização de Banco de Dados | Design practice that avoids repeated or comma-separated values by using related tables. |
| Deployment | Implantação | Process of publishing the application online, especially through Render.com in this course. |
| Dynamic Content | Conteúdo Dinâmico | HTML output generated from templates and data rather than fixed static files. |
| Edit Form | Formulário de Edição | Form populated with an existing record so the user can update it. |
| EJS | EJS | Template engine used with Express to generate HTML on the server. |
| EJS Partials | Partials do EJS | Reusable EJS template fragments such as headers and footers. |
| EJS Syntax | Sintaxe do EJS | Special tags such as escaped output and includes used inside EJS templates. |
| EJS Template | Template EJS | View file that receives data and produces HTML for the browser. |
| Encryption | Criptografia | Reversible protection of data using a key; contrasted with hashing in password security. |
| Environment Variable | Variável de Ambiente | Configuration value stored outside code, used for secrets and deployment-specific settings. |
| Error Handling Middleware | Middleware de Tratamento de Erros | Express middleware designed to handle errors and send an appropriate response. |
| Express | Express | Node.js web framework used for routing, middleware, static files, and server-side rendering. |
| Express Router | Roteador do Express | Express feature used to organize related routes in separate modules. |
| Express Routing | Roteamento do Express | Mapping of HTTP methods and URL paths to route handler functions. |
| Flash Message | Mensagem Flash | Temporary session-based message shown once after a redirect or completed action. |
| Foreign Key | Chave Estrangeira | Database column that links a row to a related row in another table. |
| Form Action | Ação do Formulário | URL where a form submits its data. |
| Form Method | Método do Formulário | HTTP method, usually GET or POST, used when a form is submitted. |
| Form Population | Preenchimento de Formulário | Loading existing data into form fields so users can edit records. |
| Form Submission | Envio de Formulário | Process where browser sends user-entered form data to the server. |
| GET | GET | HTTP method used to request or view data without changing server state. |
| Git | Git | Version control system used to track project changes. |
| GitHub | GitHub | Remote repository platform used for storing and submitting course project code. |
| Hashing | Hashing | One-way transformation used for securely storing passwords. |
| Header | Cabeçalho | Reusable page section or HTTP metadata, depending on the context. |
| Hosted Environment Variables | Variáveis de Ambiente Hospedadas | Environment variables configured on Render or another hosting platform. |
| HTML | HTML | Markup language generated by static files or EJS templates and sent to the browser. |
| HTTP | HTTP | Protocol used by browsers and servers to exchange requests and responses. |
| HTTP Headers | Cabeçalhos HTTP | Metadata sent with HTTP requests and responses. |
| HTTP Method | Método HTTP | Verb such as GET or POST that indicates the purpose of a request. |
| HTTP Request | Requisição HTTP | Message sent from the browser to the server asking for a resource or action. |
| HTTP Response | Resposta HTTP | Message sent from the server back to the browser after processing a request. |
| HTTP Status Code | Código de Status HTTP | Numeric response code indicating success, redirect, client error, or server error. |
| JavaScript | JavaScript | Programming language used in Node.js on the server and in browser-side behavior. |
| Join Table | Tabela de Junção | Table that connects two entities in a many-to-many database relationship. |
| Local Environment | Ambiente Local | Student's own development machine where the application is built and tested. |
| Login | Login | Process where a user submits credentials to start an authenticated session. |
| Login State | Estado de Login | Application awareness of whether a user is currently authenticated. |
| Many-to-Many Relationship | Relacionamento Muitos-para-Muitos | Database relationship where records on both sides can connect to multiple records on the other side. |
| Middleware | Middleware | Express function that processes requests and responses before or after route handlers. |
| Middleware Order | Ordem do Middleware | Sequence in which middleware is registered, which controls the request processing pipeline. |
| Middleware Pipeline | Pipeline de Middleware | Ordered chain of middleware functions that a request passes through. |
| Model | Modelo | MVC component responsible for database queries and data access logic. |
| MVC | MVC | Architecture pattern separating Model, View, and Controller responsibilities. |
| next() | next() | Express function that passes control from one middleware function to the next. |
| Node.js | Node.js | JavaScript runtime used to run the backend server. |
| Nodemon | Nodemon | Development tool that restarts the Node.js server automatically when files change. |
| NOT NULL Constraint | Restrição NOT NULL | Database rule requiring a column to contain a value. |
| NPM | NPM | Node package manager used to install dependencies and run project scripts. |
| One-to-Many Relationship | Relacionamento Um-para-Muitos | Database relationship where one record can be associated with many records in another table. |
| Organization | Organização | Course project entity representing a group that sponsors service projects. |
| Parameterized Query | Consulta parametrizada | SQL query style that safely separates user input from SQL code to prevent injection. |
| Password Hash | Hash de Senha | Stored hashed version of a password used for login verification. |
| Password Security | Segurança de Senhas | Practices such as hashing with bcrypt and never storing plaintext passwords. |
| Path | Caminho | Location string used to identify files, directories, or URL routes. |
| pgAdmin | pgAdmin | PostgreSQL administration tool used to inspect and manage course databases. |
| POST | POST | HTTP method used to submit data that creates or changes server-side state. |
| Post-Redirect-Get Pattern | Padrão Post-Redirect-Get | Pattern where the server redirects after processing a POST to prevent duplicate form submissions. |
| PostgreSQL | PostgreSQL | Relational database system used in the course project. |
| Primary Key | Chave Primária | Database column or set of columns that uniquely identifies each row. |
| Protected Route | Rota Protegida | Route that requires authentication or authorization before access is allowed. |
| Public Folder | Pasta Pública | Express static directory where browser-accessible assets such as CSS and images are stored. |
| Push | Push | Git action that sends local commits to a remote repository such as GitHub. |
| Query Parameter | Parâmetro de Consulta | Optional URL value after a question mark, often used for filtering or extra request details. |
| Redirect | Redirecionamento | Response that tells the browser to request a different URL. |
| Relative Path | Caminho Relativo | File or URL path interpreted from the current location. |
| Render | Render | Hosting platform used in the course to deploy Node.js applications and PostgreSQL databases. |
| render | renderizar | Express/EJS action that generates HTML from a template and data. |
| Repository | Repositório | Git project storage location, often hosted remotely on GitHub. |
| Request Body | Corpo da Requisição | Data submitted in a request, commonly from POST form submissions. |
| Request-Response Lifecycle | Ciclo Requisição-Resposta | Sequence where the browser sends a request, the server processes it, and the browser receives a response. |
| res.locals | res.locals | Express object used to make values available to views during a response. |
| Role | Papel | Named permission group such as user or admin. |
| Role-Based Access Control | Controle de Acesso Baseado em Papéis | Authorization strategy that grants permissions according to assigned user roles. |
| Root-Relative Path | Caminho Relativo à Raiz | URL path that starts from the site root, often beginning with a slash. |
| Route | Rota | URL path and HTTP method combination handled by the Express application. |
| Route Handler | Manipulador de Rota | Function that runs when a matching Express route receives a request. |
| Route Parameter | Parâmetro de Rota | Required value embedded in the URL path, such as an ID in `/projects/42`. |
| Router | Roteador | MVC-adjacent component that directs incoming requests to the correct controller function. |
| Salt | Salt | Random value used with hashing to make password hashes harder to attack. |
| Server | Servidor | Backend program that receives requests, accesses data, and sends responses. |
| Server Error | Erro do Servidor | HTTP 5xx status category indicating that something failed on the server. |
| Server-Side Rendering | Renderização no Lado do Servidor | Generating complete HTML on the server before sending it to the browser. |
| Server-Side Validation | Validação no Lado do Servidor | Server-based form checking required for security and data integrity. |
| Service Project | Projeto de Serviço | Course project entity representing a volunteer or service opportunity. |
| Session | Sessão | Server-side storage that remembers user state across separate HTTP requests. |
| Session Data | Dados da Sessão | Information stored on the server for a user's active session. |
| Session ID | ID de Sessão | Identifier sent to the browser, usually in a cookie, so the server can find session data. |
| setup.sql | setup.sql | SQL script used to recreate database tables, relationships, and starter data. |
| SQL | SQL | Language used to create tables, insert records, and query relational databases. |
| SQL Injection | Injeção de SQL | Attack where malicious input is interpreted as SQL code by the database. |
| Static Directory | Diretório Estático | Folder configured in Express to serve files directly without individual route handlers. |
| Static Files | Arquivos Estáticos | Files such as CSS, images, and client-side scripts served directly to the browser. |
| Status Update | Atualização de Status | Short course reflection or report on project progress. |
| String Concatenation | Concatenação de Strings | Joining strings manually, risky when used to build SQL queries with user input. |
| Table | Tabela | Database structure made of rows and columns. |
| Team Activity | Atividade em Equipe | Weekly collaborative work where students review and implement course project features. |
| Template Engine | Motor de Templates | Tool such as EJS that combines templates with data to generate HTML. |
| Testing Account | Conta de Teste | Account provided so instructors can verify authentication and authorization features. |
| URL | URL | Web address used by the browser to request a page or resource. |
| User Model | Modelo de Usuário | Model layer code responsible for user registration, lookup, and authentication queries. |
| User Registration | Cadastro de Usuário | Feature where new users create accounts and passwords are hashed before storage. |
| Validation | Validação | Checking submitted data for required fields, correct format, and acceptable values. |
| View | Visão | MVC component responsible for presentation, usually implemented with EJS templates. |
| View Page Source | Ver Código-Fonte da Página | Browser feature used to inspect the final HTML sent by the server. |
| VS Code | VS Code | Code editor used for course project development. |
| Web Backend Development | Desenvolvimento Backend Web | Course focus area covering server-side applications, databases, routing, authentication, and deployment. |