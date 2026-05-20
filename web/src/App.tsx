import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Alerts from './pages/Alerts';
import Home from './pages/Home';
import ObjectDetail from './pages/ObjectDetail';
import Risk from './pages/Risk';

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/risk" element={<Risk />} />
          <Route path="/objects/:designation" element={<ObjectDetail />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

function NotFound() {
  return (
    <section className="page">
      <h1>Not found</h1>
      <p>That URL doesn't match anything in the current snapshot.</p>
    </section>
  );
}
