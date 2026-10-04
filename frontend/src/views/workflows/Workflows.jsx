import { useNavigate } from "react-router-dom";
import { FaFileImage, FaImages, FaMagic, FaBorderAll, FaExpandArrowsAlt, FaDrawPolygon, FaCouch } from "react-icons/fa";

import Card from "../../components/ui/Card";

const basicWorkflows = [
  { path: "text-to-image", icon: FaFileImage, title: "Text to Image", description: "Generate an image based on a text prompt" },
  { path: "image-to-image", icon: FaImages, title: "Image to Image", description: "Transform an input image by providing a text prompt." },
  { path: "inpainting", icon: FaMagic, title: "Inpainting", description: "Inpainting lets you paint out areas on the image that you want to change." },
];

const advancedWorkflows = [
  { path: "furniture-replace", icon: FaCouch, title: "Furniture Replace", description: "Replace selected furniture with a prompt or catalog reference." },
  { path: "control-net", icon: FaBorderAll, title: "Control Net", description: "Guided image generation using structural input like pose, depth or edges." },
  { path: "outpainting", icon: FaExpandArrowsAlt, title: "Outpainting", description: "Extend your image beyond its borders while keeping the original style and details intact." },
  { path: "canvas", icon: FaDrawPolygon, title: "Canvas", description: "Use canvas to track your workflow" },
];

const WorkflowGrid = ({ workflows }) => {
  const navigate = useNavigate();

  return (
    <div className="w-full grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-6">
      {workflows.map(({ path, icon: Icon, title, description }) => (
        <Card key={path} className="hover:border-foreground/20 transition-colors">
          <button
            onClick={() => navigate(`/views/workflows/${path}`)}
            className="w-full flex flex-col items-start gap-3 p-6 text-left cursor-pointer"
          >
            <div className="bg-accent/15 text-accent flex items-center justify-center p-3 rounded-lg">
              <Icon className="w-6 h-6" />
            </div>
            <h3 className="font-serif text-lg font-semibold text-foreground">{title}</h3>
            <p className="text-muted text-sm">{description}</p>
          </button>
        </Card>
      ))}
    </div>
  );
};

const Workflows = () => {
  return (
    <div className="w-full min-h-screen flex flex-col p-5 gap-5">
      <h1 className="font-serif font-bold text-3xl">Basic workflows</h1>
      <WorkflowGrid workflows={basicWorkflows} />

      <h1 className="font-serif font-bold text-3xl mt-4">Advanced workflows</h1>
      <WorkflowGrid workflows={advancedWorkflows} />
    </div>
  );
};

export default Workflows;
