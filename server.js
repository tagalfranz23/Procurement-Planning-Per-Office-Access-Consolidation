/** PPMP real-time notification and PDF export service. */
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const PDFDocument = require('pdfkit');

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*', methods: ['GET', 'POST'] } });
const connectedUsers = new Map();

io.on('connection', (socket) => {
  connectedUsers.set(socket.id, { id: socket.id, joinedAt: new Date() });
  socket.emit('welcome', { message: 'Connected to PPMP Notification Hub', users: connectedUsers.size, timestamp: new Date().toISOString() });
  io.emit('user_count', { count: connectedUsers.size });
  socket.on('ppmp_action', (data) => io.emit('ppmp_notification', { ...data, type: data.action, timestamp: new Date().toISOString() }));
  socket.on('status_change', (data) => io.emit('ppmp_notification', { ...data, type: 'status_change', timestamp: new Date().toISOString() }));
  socket.on('disconnect', () => {
    connectedUsers.delete(socket.id);
    io.emit('user_count', { count: connectedUsers.size });
  });
});

app.post('/api/export/pdf', (req, res) => {
  const { items = [], college_name: collegeName = 'All Colleges', title = 'PPMP Report' } = req.body;
  const total = items.reduce((sum, item) => sum + Number(item.total_cost || 0), 0);
  const document = new PDFDocument({ margin: 40, size: 'LEGAL', layout: 'landscape' });
  res.setHeader('Content-Type', 'application/pdf');
  res.setHeader('Content-Disposition', `attachment; filename="PPMP_${Date.now()}.pdf"`);
  document.pipe(res);
  document.fontSize(18).text(title, { align: 'center' });
  document.fontSize(10).text(`${collegeName} | Generated ${new Date().toLocaleDateString('en-PH')}`, { align: 'center' });
  document.moveDown().fontSize(11).text(`Total records: ${items.length}    Total procurement budget: PHP ${total.toLocaleString('en-PH', { minimumFractionDigits: 2 })}`);
  document.moveDown();
  if (!items.length) {
    document.text('No procurement records available.');
  } else {
    items.forEach((item, index) => {
      document.fontSize(9).text(`${index + 1}. ${item.item_description} | ${item.college_code || ''} | PHP ${Number(item.total_cost || 0).toLocaleString('en-PH', { minimumFractionDigits: 2 })}`);
    });
  }
  document.end();
});

app.get('/api/ws-status', (req, res) => res.json({ connected_clients: connectedUsers.size }));

const port = process.env.NODE_PORT || 3001;
server.listen(port, () => console.log(`PPMP Node.js server on port ${port}`));
